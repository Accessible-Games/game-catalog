"""Compile catalog entries into the gzipped index published on GitHub Pages."""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from catalog.config import INDEX_DOMAIN
from catalog.entries import ROOT, EntryLoadError, load_entries
from catalog.validate import validate_entries

SCHEMA_VERSION = 1


def build_index(entries: dict[str, dict], generated_at: str) -> dict:
    extras: dict[str, list[dict]] = {}
    for key in sorted(entries):
        target = entries[key].get("extends")
        if target:
            extras.setdefault(target, []).append(
                {"id": entries[key]["id"], "required": bool(entries[key].get("required", False))}
            )
    out = []
    for key in sorted(entries):
        entry = copy.deepcopy(entries[key])
        entry["extras"] = sorted(extras.get(entry["id"], []), key=lambda e: e["id"])
        out.append(entry)
    out.sort(key=lambda e: e["id"])
    return {"schema_version": SCHEMA_VERSION, "generated_at": generated_at, "entries": out}


def write_index(index: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(index, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    data = gzip.compress(raw, mtime=0)
    gz_path = out_dir / "index.json.gz"
    gz_path.write_bytes(data)
    meta = {
        "schema_version": index["schema_version"],
        "generated_at": index["generated_at"],
        "entry_count": len(index["entries"]),
        "sha256": hashlib.sha256(data).hexdigest(),
        "index_url": "index.json.gz",
    }
    meta_path = out_dir / "index-meta.json"
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8", newline="\n")
    (out_dir / "CNAME").write_text(INDEX_DOMAIN + "\n", encoding="utf-8", newline="\n")
    return gz_path, meta_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="catalog-index", description="Build the catalog index.")
    parser.add_argument("--entries", type=Path, default=ROOT / "entries")
    parser.add_argument("--out", type=Path, default=Path("site"))
    parser.add_argument(
        "--generated-at",
        default=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    args = parser.parse_args(argv)
    try:
        entries = load_entries(args.entries)
    except EntryLoadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    problems = validate_entries(entries)
    if problems:
        for p in problems:
            print(f"{p.entry_id}: {p.message}", file=sys.stderr)
        return 1
    write_index(build_index(entries, args.generated_at), args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
