"""FastAPI serving layer (docs/PLAN.md §8).

Run (dev machine, localhost only):
    python -m rva_chat.serve.app

Run for real LAN access (deployment target — see PLAN.md §7's access-mode
decision):
    uvicorn rva_chat.serve.app:app --host 0.0.0.0 --port 8000

Binding to 0.0.0.0 exposes this to whatever network the host is on. Never put
it behind a tunnel or expose it past the LAN — see PLAN.md §7/§8.

Why /chat doesn't stream LLM tokens despite PLAN.md §8 saying "streams
tokens": a guardrail that can only judge the *complete* answer can't un-send
words a user already saw. Cards stream immediately (the real UX goal — a
visible response in <1s while the model is still running); the prose arrives
as one checked unit once generation finishes. See templates.py and §8 in
PLAN.md, updated to match.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import pathlib
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from rva_chat.generate.guardrails import check_grounded, is_refusal
from rva_chat.generate.llm import LLMConfig, OllamaClient
from rva_chat.generate.prompt import build_messages
from rva_chat.retrieve.corpus import Chunk, load_corpus
from rva_chat.retrieve.search import HybridSearcher
from rva_chat.serve.telemetry import Counters, QueryLog
from rva_chat.serve.templates import render_page

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
ENTITIES_DIR = REPO_ROOT / "data" / "entities"
LOGS_DIR = REPO_ROOT / "logs"
STALE_DAYS_DEFAULT = 180  # matches the "~6 months" staleness note in PLAN.md §3d

MAX_QUERY_LEN = 500


@asynccontextmanager
async def lifespan(app: FastAPI):
    chunks = load_corpus(ENTITIES_DIR)
    app.state.chunks = chunks
    app.state.searcher = HybridSearcher(chunks)  # BM25-only until an embedder is wired in
    app.state.llm = OllamaClient(LLMConfig())
    app.state.counters = Counters()
    app.state.query_log = QueryLog(LOGS_DIR)
    app.state.start_time = time.time()
    yield


app = FastAPI(title="RVA Sustainability Chat", lifespan=lifespan)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _card_dict(c: Chunk) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "url": c.url,
        "topics": c.topics,
        "volunteer": c.volunteer,
        "notes_public": c.notes_public,
        "last_verified": c.last_verified,
    }


class ChatResult:
    __slots__ = ("text", "grounded", "reason", "llm_error")

    def __init__(self, text: str | None, grounded: bool | None, reason: str | None, llm_error: bool):
        self.text = text
        self.grounded = grounded
        self.reason = reason
        self.llm_error = llm_error


async def _generate_and_check(llm: OllamaClient, query: str, retrieved: list[Chunk]) -> ChatResult:
    """Shared by the SSE and no-JS endpoints so the reachability/guardrail
    branching logic exists in exactly one place."""
    if not llm.is_reachable():
        return ChatResult(None, None, "The language model isn't running — showing sources only.", True)

    messages = build_messages(query, retrieved)
    try:
        answer = await asyncio.to_thread(llm.chat, messages)
    except Exception as e:  # noqa: BLE001 — any backend failure degrades to cards-only, never a 500
        return ChatResult(None, None, f"The language model returned an error: {e}", True)

    ok, reason = check_grounded(answer, retrieved)
    if ok:
        return ChatResult(answer, True, reason, False)
    return ChatResult(None, False, reason, False)


def _record(
    app: FastAPI,
    *,
    query: str,
    retrieved: list[Chunk],
    result: ChatResult | None,
    refused: bool,
    latency_ms: float,
    no_log: bool,
) -> None:
    app.state.counters.record(
        latency_ms=latency_ms,
        refused=refused,
        dropped=bool(result and result.grounded is False),
        llm_error=bool(result and result.llm_error),
    )
    app.state.query_log.log(
        query=query,
        matched_entity_ids=[c.id for c in retrieved],
        grounded=(result.grounded if result else True),
        latency_ms=latency_ms,
        skip=no_log,
    )


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return render_page()


@app.get("/chat")
async def chat(
    request: Request,
    q: str = Query(..., min_length=1, max_length=MAX_QUERY_LEN),
    no_log: int = 0,
):
    searcher: HybridSearcher = request.app.state.searcher
    llm: OllamaClient = request.app.state.llm

    async def event_stream():
        t0 = time.time()
        results = searcher.search(q, top_k=5)
        retrieved = [r.chunk for r in results]
        yield _sse("cards", {"cards": [_card_dict(c) for c in retrieved]})

        if not retrieved:
            yield _sse("answer", {"text": "I don't have that in my sources.", "grounded": True})
            yield _sse("done", {})
            _record(
                request.app, query=q, retrieved=[], result=None, refused=True,
                latency_ms=(time.time() - t0) * 1000, no_log=bool(no_log),
            )
            return

        result = await _generate_and_check(llm, q, retrieved)
        if result.text is not None:
            yield _sse("answer", {"text": result.text, "grounded": result.grounded})
        else:
            yield _sse("answer", {"text": None, "grounded": result.grounded, "reason": result.reason})
        yield _sse("done", {})
        _record(
            request.app, query=q, retrieved=retrieved, result=result,
            refused=bool(result.text and is_refusal(result.text)),
            latency_ms=(time.time() - t0) * 1000, no_log=bool(no_log),
        )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/chat-plain", response_class=HTMLResponse)
async def chat_plain(request: Request):
    form = await request.form()
    q = str(form.get("q", "")).strip()[:MAX_QUERY_LEN]
    no_log = form.get("no_log") == "1"

    if not q:
        return render_page()

    t0 = time.time()
    searcher: HybridSearcher = request.app.state.searcher
    llm: OllamaClient = request.app.state.llm

    results = searcher.search(q, top_k=5)
    retrieved = [r.chunk for r in results]

    if not retrieved:
        _record(
            request.app, query=q, retrieved=[], result=None, refused=True,
            latency_ms=(time.time() - t0) * 1000, no_log=no_log,
        )
        return render_page(initial_query=q, answer_text="I don't have that in my sources.")

    result = await _generate_and_check(llm, q, retrieved)
    _record(
        request.app, query=q, retrieved=retrieved, result=result,
        refused=bool(result.text and is_refusal(result.text)),
        latency_ms=(time.time() - t0) * 1000, no_log=no_log,
    )
    return render_page(
        initial_query=q,
        cards=retrieved,
        answer_text=result.text if result.text is not None else result.reason,
        answer_dropped=(result.text is None),
    )


@app.get("/healthz")
async def healthz(request: Request) -> dict:
    llm: OllamaClient = request.app.state.llm
    return {
        "status": "ok",
        "corpus_size": len(request.app.state.chunks),
        "llm_reachable": llm.is_reachable(),
        "model": llm.config.model,
        "uptime_s": round(time.time() - request.app.state.start_time, 1),
    }


@app.get("/metrics")
async def metrics(request: Request) -> dict:
    return request.app.state.counters.snapshot()


@app.get("/admin/stale")
async def admin_stale(request: Request, days: int = STALE_DAYS_DEFAULT) -> dict:
    today = datetime.date.today()
    stale = []
    for c in request.app.state.chunks:
        try:
            verified = datetime.date.fromisoformat(c.last_verified)
        except (ValueError, TypeError):
            stale.append({"id": c.id, "name": c.name, "last_verified": c.last_verified, "days_stale": None})
            continue
        age = (today - verified).days
        if age > days:
            stale.append({"id": c.id, "name": c.name, "last_verified": c.last_verified, "days_stale": age})
    return {"threshold_days": days, "stale_count": len(stale), "stale": stale}


if __name__ == "__main__":
    # Dev convenience: localhost only. Pass --host 0.0.0.0 via plain uvicorn
    # (see module docstring) for actual LAN deployment.
    uvicorn.run(app, host="127.0.0.1", port=8000)
