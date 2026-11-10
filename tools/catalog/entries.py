"""Load and write catalog entry files."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENTRY_SCHEMA_PATH = ROOT / "schema" / "entry.schema.json"

ENTRY_KEY_ORDER: tuple[str, ...] = (
    "id", "kind", "title", "developer", "genres", "year", "description", "version",
    "self_updating", "pricing", "tags", "languages", "contains", "unsupported", "warning",
    "links", "sources", "launch", "dependencies", "extends", "install_into", "required",
    "detect", "checkver",
)


class EntryLoadError(Exception):
    """An entry file could not be read or parsed."""

    def __init__(self, path: Path, message: str):
        super().__init__(f"{path}: {message}")
        self.path = path


def load_entries(entries_dir: Path) -> dict[str, dict]:
    """Load every *.json in entries_dir, keyed by filename stem."""
    result: dict[str, dict] = {}
    for path in sorted(Path(entries_dir).glob("*.json")):
        try:
            result[path.stem] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise EntryLoadError(path, str(exc)) from exc
    return result


def _ordered(entry: dict) -> dict:
    known = {k: entry[k] for k in ENTRY_KEY_ORDER if k in entry}
    known.update({k: v for k, v in entry.items() if k not in known})
    return known


def write_entry(entries_dir: Path, entry: dict, *, overwrite: bool = False) -> Path:
    """Write entry to <entries_dir>/<id>.json with canonical formatting."""
    path = Path(entries_dir) / f"{entry['id']}.json"
    text = json.dumps(_ordered(entry), indent=2, ensure_ascii=False) + "\n"
    with path.open("w" if overwrite else "x", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path


def load_schema() -> dict:
    return json.loads(ENTRY_SCHEMA_PATH.read_text(encoding="utf-8"))
