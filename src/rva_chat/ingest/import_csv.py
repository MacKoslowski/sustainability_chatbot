"""Import hand-maintained resource spreadsheets into entity YAML records.

One-way: CSV -> data/entities/*.yaml. Never writes back to the CSV. Re-running is
idempotent (same input -> same output), because `id` is derived from a slug of
`name`, not assigned incrementally.

Per docs/PLAN.md §3d: fix mechanical issues here (URL scheme, whitespace) but never
invent facts (a corrected name, a guessed URL) — those get fixed in the spreadsheet
by a human. A row this importer can't validate is reported with its row number and
skipped, not silently patched.
"""

from __future__ import annotations

import csv
import dataclasses
import datetime
import pathlib
import re
import sys
from urllib.parse import urlparse

REQUIRED_COLUMNS = ["name", "description", "scope", "url", "notes_public", "notes_internal"]
VALID_SCOPES = {"local", "online"}

# Editorial tags for the current 15-row resources.csv. The spreadsheet has no
# topics/jurisdiction/volunteer columns yet (see PLAN.md §3d — add them there
# when the sheet grows), so until then this table is the source for those three
# fields, keyed by the row's exact `name`. Anything not listed falls back to the
# conservative defaults in `_default_tags` below. These are first-pass editorial
# calls, not verified facts — worth a human review pass, not a "last_verified" claim.
EDITORIAL_TAGS: dict[str, dict] = {
    "The James River Association": {"topics": ["water", "habitat", "advocacy"], "volunteer": False},
    "Undoing Ruin": {"topics": ["habitat", "education"], "volunteer": False},
    "Moulton Hot Natives": {"topics": ["habitat"], "volunteer": False},
    "Ecosia": {"topics": ["habitat"], "volunteer": False, "jurisdiction": []},
    "Shalom Farms": {"topics": ["food"], "volunteer": True},
    "Purring Hearts VA": {"topics": ["reuse"], "volunteer": True},
    "Adopt-a-Highway (VDOT)": {"topics": ["waste", "advocacy"], "volunteer": True},
    "Too Good to Go": {"topics": ["food", "waste"], "volunteer": False, "jurisdiction": []},
    "Leave the Leaves / Xerces Society": {"topics": ["habitat", "education"], "volunteer": False, "jurisdiction": []},
    "Climate Fresk": {"topics": ["education"], "volunteer": False, "jurisdiction": []},
    "Acorn Host": {"topics": ["energy"], "volunteer": False, "jurisdiction": []},
    "Viridiant": {"topics": ["energy", "education"], "volunteer": False},
    "Rag & Bones Bicycle Cooperative": {"topics": ["reuse", "transport"], "volunteer": True},
    "SCRAP RVA (Richmond Creative Reuse Center)": {"topics": ["reuse", "education"], "volunteer": False},
}


@dataclasses.dataclass
class ImportError_:
    row_number: int
    name: str
    problem: str


@dataclasses.dataclass
class Entity:
    id: str
    name: str
    type: str
    scope: str
    jurisdiction: list[str]
    topics: list[str]
    volunteer: bool
    description: str
    url: str
    notes_public: str | None
    notes_internal: str | None
    source: str
    source_url: str
    last_verified: str
    verified_by: str

    def to_yaml_dict(self) -> dict:
        d = dataclasses.asdict(self)
        # Drop empty optional fields so generated YAML stays readable.
        if not d["notes_public"]:
            d.pop("notes_public")
        if not d["notes_internal"]:
            d.pop("notes_internal")
        return d


def slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[()&]", " ", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _normalize_url(raw: str) -> str | None:
    """Mechanical fix only: add a missing scheme. Never fabricates a URL."""
    raw = raw.strip()
    if not raw:
        return None
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw):
        raw = "https://" + raw
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.netloc or " " in parsed.netloc:
        return None
    return raw


def _default_tags(scope: str) -> dict:
    return {
        "topics": ["general"],
        "jurisdiction": [] if scope == "online" else ["regional"],
        "volunteer": False,
    }


def import_csv(csv_path: pathlib.Path, out_dir: pathlib.Path) -> tuple[list[Entity], list[ImportError_]]:
    entities: list[Entity] = []
    errors: list[ImportError_] = []
    today = datetime.date.today().isoformat()

    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(
                f"{csv_path}: missing required column(s) {missing}. "
                f"Found columns: {reader.fieldnames}"
            )

        for row_number, row in enumerate(reader, start=2):  # header is row 1
            name = (row.get("name") or "").strip()
            if not name:
                errors.append(ImportError_(row_number, "(blank)", "empty name"))
                continue

            # DictReader stuffs any columns past the header under key None (too many
            # commas — usually an unquoted comma inside a field) and leaves declared
            # columns as None if the row has too few (a missing trailing comma/quote).
            # Both are silent data corruption if not caught here — catch them.
            if row.get(None):
                errors.append(
                    ImportError_(
                        row_number, name,
                        f"more columns than the header — likely an unquoted comma "
                        f"inside a field; extra value(s): {row[None]!r}",
                    )
                )
                continue
            if any(row.get(col) is None for col in REQUIRED_COLUMNS):
                errors.append(ImportError_(row_number, name, "fewer columns than the header"))
                continue

            scope = (row.get("scope") or "").strip().lower()
            if scope not in VALID_SCOPES:
                errors.append(ImportError_(row_number, name, f"scope {scope!r} not in {VALID_SCOPES}"))
                continue

            url = _normalize_url(row.get("url") or "")
            if url is None:
                errors.append(ImportError_(row_number, name, f"invalid url: {row.get('url')!r}"))
                continue

            description = (row.get("description") or "").strip()
            if not description:
                errors.append(ImportError_(row_number, name, "empty description"))
                continue

            tags = {**_default_tags(scope), **EDITORIAL_TAGS.get(name, {})}

            entities.append(
                Entity(
                    id=slugify(name),
                    name=name,
                    type="org",
                    scope=scope,
                    jurisdiction=tags["jurisdiction"],
                    topics=tags["topics"],
                    volunteer=tags["volunteer"],
                    description=description,
                    url=url,
                    notes_public=(row.get("notes_public") or "").strip() or None,
                    notes_internal=(row.get("notes_internal") or "").strip() or None,
                    source=csv_path.name,
                    source_url=url,
                    last_verified=today,
                    verified_by="import",
                )
            )

    out_dir.mkdir(parents=True, exist_ok=True)
    import yaml

    for entity in entities:
        out_path = out_dir / f"{entity.id}.yaml"
        with out_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(
                entity.to_yaml_dict(), f, sort_keys=False, allow_unicode=True, width=100
            )

    return entities, errors


def main() -> int:
    repo_root = pathlib.Path(__file__).resolve().parents[3]
    csv_path = repo_root / "data" / "imports" / "resources.csv"
    out_dir = repo_root / "data" / "entities"

    entities, errors = import_csv(csv_path, out_dir)

    print(f"Imported {len(entities)} entities from {csv_path} -> {out_dir}")
    for e in entities:
        flags = []
        if e.notes_internal:
            flags.append("has-internal-note")
        print(f"  [{e.scope:6}] {e.name}  ({e.id}.yaml){' ' + ' '.join(flags) if flags else ''}")

    if errors:
        print(f"\n{len(errors)} row(s) skipped — fix these in the spreadsheet, not here:")
        for err in errors:
            print(f"  row {err.row_number} ({err.name}): {err.problem}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
