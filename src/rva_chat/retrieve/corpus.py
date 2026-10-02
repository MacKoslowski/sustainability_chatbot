"""Load entity YAML (and, later, prose docs) into retrievable chunks.

Per docs/PLAN.md §3a/§3c: plain text is the source of truth and the runtime
store — no database. This loads everything into memory at startup; at the
current corpus size (dozens to low hundreds of chunks) that's milliseconds.

Each chunk is self-describing (name, scope, topics baked into the text itself)
per the chunking note in §3b, so a chunk still makes sense once it's pulled out
of context and handed to the model alone.
"""

from __future__ import annotations

import dataclasses
import pathlib

import yaml


@dataclasses.dataclass
class Chunk:
    id: str
    text: str  # what gets embedded/indexed/shown to the model
    name: str
    url: str
    scope: str
    jurisdiction: list[str]
    topics: list[str]
    volunteer: bool
    notes_public: str | None
    last_verified: str


def _entity_to_chunk(entity: dict) -> Chunk:
    topics_str = ", ".join(entity.get("topics", [])) or "general"
    header = f"{entity['name']} ({entity['scope']}; topics: {topics_str})"
    body = entity["description"]
    text = f"{header}. {body}"
    if entity.get("notes_public"):
        text += f" {entity['notes_public']}"
    return Chunk(
        id=entity["id"],
        text=text,
        name=entity["name"],
        url=entity.get("url", ""),
        scope=entity.get("scope", "local"),
        jurisdiction=entity.get("jurisdiction", []),
        topics=entity.get("topics", []),
        volunteer=entity.get("volunteer", False),
        notes_public=entity.get("notes_public"),
        last_verified=entity.get("last_verified", ""),
    )


def load_corpus(entities_dir: pathlib.Path) -> list[Chunk]:
    """Load every *.yaml in entities_dir into a flat list of Chunks.

    `notes_internal` is deliberately never read here — it must never enter
    retrieval, and therefore never reach the model or the user. See PLAN.md §3a.
    """
    chunks: list[Chunk] = []
    for path in sorted(entities_dir.glob("*.yaml")):
        with path.open(encoding="utf-8") as f:
            entity = yaml.safe_load(f)
        if not entity:
            continue
        chunks.append(_entity_to_chunk(entity))
    return chunks
