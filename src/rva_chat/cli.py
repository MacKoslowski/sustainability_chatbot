"""End-to-end chat loop in a terminal — docs/PLAN.md Phase 1's "done when."

Run: python -m rva_chat.cli
"""

from __future__ import annotations

import pathlib

from rva_chat.generate.cards import render_cards
from rva_chat.generate.guardrails import check_grounded
from rva_chat.generate.llm import LLMConfig, OllamaClient
from rva_chat.generate.prompt import build_messages
from rva_chat.retrieve.corpus import load_corpus
from rva_chat.retrieve.search import HybridSearcher

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ENTITIES_DIR = REPO_ROOT / "data" / "entities"


def main() -> None:
    chunks = load_corpus(ENTITIES_DIR)
    print(f"Loaded {len(chunks)} entities from {ENTITIES_DIR}")
    if not chunks:
        print("No entities found — run: python -m rva_chat.ingest.import_csv")
        return

    searcher = HybridSearcher(chunks)  # BM25-only until an embedder is wired in
    llm = OllamaClient(LLMConfig())

    if not llm.is_reachable():
        print(
            f"\nWARNING: can't reach Ollama at {llm.config.base_url}.\n"
            "Start it with `ollama serve`, and make sure the model is pulled:\n"
            f"  ollama pull {llm.config.model}\n"
            "Retrieval still works without it — cards will show, but no prose answer.\n"
        )

    print("\nAsk about recycling, disposal, or getting involved in Richmond, VA.")
    print("Type 'quit' to exit.\n")

    while True:
        try:
            query = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not query:
            continue
        if query.lower() in ("quit", "exit"):
            break

        results = searcher.search(query, top_k=5)
        retrieved = [r.chunk for r in results]

        if not retrieved:
            print("\nI don't have that in my sources.\n")
            continue

        if llm.is_reachable():
            messages = build_messages(query, retrieved)
            try:
                answer = llm.chat(messages)
            except Exception as e:  # noqa: BLE001 — surface any backend failure, keep CLI alive
                print(f"\n[LLM error: {e}]\n")
                answer = None
        else:
            answer = None

        if answer:
            ok, reason = check_grounded(answer, retrieved)
            if ok:
                print(f"\n{answer}\n")
                if reason:
                    print(f"[note: {reason}]")
            else:
                print(f"\n[dropped ungrounded answer: {reason}]")
                print("Here's what I found instead:\n")

        print(render_cards(retrieved))
        print()


if __name__ == "__main__":
    main()
