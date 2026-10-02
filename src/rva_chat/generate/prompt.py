"""Prompt construction. Kept short deliberately — small models degrade with
long instructions, and every system token is tokens/sec spent (docs/PLAN.md §5).
"""

from __future__ import annotations

from rva_chat.retrieve.corpus import Chunk

SYSTEM_PROMPT = """You answer questions about sustainability, recycling, and getting \
involved in the Richmond, Virginia area, using only the SOURCES below.

Rules:
- Use only facts stated in SOURCES. If SOURCES do not answer the question, say \
"I don't have that in my sources" and nothing more.
- Refer to places and organizations by name only. Never write an address, phone \
number, price, or set of hours — those are shown automatically after your answer.
- 2 to 4 sentences. Plain language. No bullet lists, no preamble."""


def format_sources(chunks: list[Chunk]) -> str:
    lines = []
    for i, c in enumerate(chunks, start=1):
        lines.append(f"[{i}] ({c.scope}, verified {c.last_verified}) {c.text}")
    return "\n".join(lines)


def build_messages(query: str, chunks: list[Chunk]) -> list[dict]:
    sources = format_sources(chunks) if chunks else "(none retrieved)"
    user_content = f"SOURCES:\n{sources}\n\nQUESTION: {query}"
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
