"""Delete mirror files that entries stopped referencing since a git commit.

The mirror never deletes on its own. After a curation change (a bundle repacked, an entry removed),
run this with the commit from before the change: it lists every mirror file that was referenced
then and is referenced by no entry now, and deletes them only with --delete.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from catalog import config
from catalog.entries import ROOT, load_entries
from catalog.mirror import WranglerUploader, mirror_keys


def referenced_keys(entries: dict[str, dict]) -> set[str]:
    return mirror_keys(entries)


def orphaned_keys(before: dict[str, dict], now: dict[str, dict]) -> list[str]:
    return sorted(referenced_keys(before) - referenced_keys(now))


def entries_at(ref: str, entries_dir: Path) -> dict[str, dict]:
    """The entries as they were at a git commit."""
    entries_dir = Path(entries_dir).resolve()
    top = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=entries_dir, check=True,
                              capture_output=True, text=True).stdout.strip())
    rel = entries_dir.relative_to(top).as_posix()
    names = subprocess.run(["git", "ls-tree", "--name-only", f"{ref}:{rel}"], cwd=top, check=True,
                           capture_output=True, text=True).stdout.split()
    result = {}
    for name in names:
        if name.endswith(".json"):
            text = subprocess.run(["git", "show", f"{ref}:{rel}/{name}"], cwd=top, check=True,
                                  capture_output=True).stdout.decode("utf-8")
            result[name[:-5]] = json.loads(text)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="catalog-prune", description=__doc__.splitlines()[0])
    parser.add_argument("--since", required=True, metavar="REF", help="git commit from before the change")
    parser.add_argument("--entries", type=Path, default=ROOT / "entries")
    parser.add_argument("--delete", action="store_true", help="actually delete (default: only list)")
    args = parser.parse_args(argv)
    orphans = orphaned_keys(entries_at(args.since, args.entries), load_entries(args.entries))
    for key in orphans:
        print(key)
    print(f"{len(orphans)} file(s) no longer referenced since {args.since}", file=sys.stderr)
    if args.delete and orphans:
        uploader = WranglerUploader(config.MIRROR_BUCKET, known_keys=orphans)
        for key in orphans:
            uploader.delete(key)
        print(f"deleted {len(orphans)} file(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
