"""Render fact cards straight from retrieved records — never from the model.

Per docs/PLAN.md §2/§5: addresses, URLs, and other specifics are rendered here,
not generated. The LLM is only ever allowed to refer to a place by name.
"""

from __future__ import annotations

from rva_chat.retrieve.corpus import Chunk


def render_card(chunk: Chunk) -> str:
    lines = [f"{chunk.name}"]
    if chunk.url:
        lines.append(f"  {chunk.url}")
    tags = []
    if chunk.topics:
        tags.append("topics: " + ", ".join(chunk.topics))
    if chunk.volunteer:
        tags.append("takes volunteers")
    if tags:
        lines.append("  " + " | ".join(tags))
    if chunk.notes_public:
        lines.append(f"  {chunk.notes_public}")
    lines.append(f"  (verified {chunk.last_verified})")
    return "\n".join(lines)


def render_cards(chunks: list[Chunk]) -> str:
    return "\n\n".join(render_card(c) for c in chunks)
