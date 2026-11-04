"""Record and check sha256/size for developer (outside) download sources.

The app verifies what it installs and notices updates through these values, so CI keeps them filled:
on a pull request, ``--check`` downloads each changed source once and fails if a recorded value is
stale; on merge, the publish workflow fills in any missing values. Files are hashed as they stream
in and never stored, so large games cost time, not disk. Mirror sources (strict, written by the
mirror tool), web sources and ``url`` installs are skipped, and forbidden hosts are never contacted.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import requests

from catalog.config import is_forbidden_url
from catalog.entries import ROOT, load_entries, write_entry
from catalog.files import HEAD_SIZE, reject_html
from catalog.http import make_session
from catalog.mirror import is_mirror_url

Mode = Literal["fill", "check", "refresh"]
Status = Literal["recorded", "updated", "ok", "missing", "mismatch", "error"]
_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class Result:
    entry_id: str
    url: str
    status: Status
    detail: str = ""

    def line(self) -> str:
        return f"{self.entry_id}: {self.status}: {self.url}" + (f" ({self.detail})" if self.detail else "")


def is_outside_download(source: object) -> bool:
    """A source whose bytes the app downloads from someone else's server."""
    if not isinstance(source, dict) or not isinstance(source.get("url"), str):
        return False
    url = source["url"]
    return (not is_mirror_url(url) and not is_forbidden_url(url) and source.get("platform") != "web"
            and (source.get("install") or {}).get("method") != "url")


def hash_url(session: requests.Session, url: str, timeout: float = 60) -> tuple[str, int]:
    """(sha256, size) of the file at url, streamed; raises for HTTP errors and web pages."""
    digest, size, head, checked = hashlib.sha256(), 0, b"", False
    with session.get(url, stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type")
        for chunk in resp.iter_content(chunk_size=_CHUNK):
            if not checked:  # stop early on a web page instead of hashing it
                head += chunk[: HEAD_SIZE - len(head)]
                if len(head) >= HEAD_SIZE:
                    reject_html(content_type, head, url)
                    checked = True
            digest.update(chunk)
            size += len(chunk)
        if not checked:
            reject_html(content_type, head, url)
    return digest.hexdigest(), size


def record_checksums(entries_dir: Path, *, session: requests.Session, mode: Mode = "fill",
                     only: Iterable[str] | None = None, write: bool = True) -> list[Result]:
    """fill: record missing values. check: change nothing; report missing and stale values.
    refresh: re-download and overwrite recorded values (accepting a changed file)."""
    wanted = set(only) if only is not None else None
    entries = load_entries(entries_dir)
    seen: dict[str, tuple[str, int] | Exception] = {}  # one download per URL per run
    results: list[Result] = []
    for entry_id, entry in entries.items():
        if wanted is not None and entry_id not in wanted:
            continue
        dirty = False
        for source in entry.get("sources") or []:
            if not is_outside_download(source):
                continue
            url = source["url"]
            has = "sha256" in source and "size" in source
            if has and mode == "fill":
                continue
            if url not in seen:
                try:
                    seen[url] = hash_url(session, url)
                except Exception as exc:  # noqa: BLE001 - reported per source; dead links are the link check's job
                    seen[url] = exc
            got = seen[url]
            if isinstance(got, Exception):
                results.append(Result(entry_id, url, "error", f"{type(got).__name__}: {got}"))
                continue
            sha256, size = got
            values = f"sha256 {sha256}, size {size}"
            if mode == "check":
                if not has:
                    results.append(Result(entry_id, url, "missing", f"recorded on merge: {values}"))
                elif (source["sha256"], source["size"]) != (sha256, size):
                    results.append(Result(entry_id, url, "mismatch",
                                          f"entry records sha256 {source['sha256']}, size {source['size']}; "
                                          f"the file has {values}"))
                else:
                    results.append(Result(entry_id, url, "ok"))
                continue
            if has and (source["sha256"], source["size"]) == (sha256, size):
                results.append(Result(entry_id, url, "ok"))
                continue
            source["sha256"], source["size"] = sha256, size
            results.append(Result(entry_id, url, "updated" if has else "recorded", values))
            dirty = True
        if dirty and write:
            write_entry(entries_dir, entry, overwrite=True)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="catalog-checksums",
                                     description="Record or check sha256/size of developer download sources.")
    parser.add_argument("--entries", type=Path, default=ROOT / "entries")
    parser.add_argument("--only", nargs="+", metavar="ID")
    parser.add_argument("--changed-from", metavar="REF", help="only entries added or changed since this git ref")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true",
                      help="write nothing; exit 1 if a recorded value does not match the file")
    mode.add_argument("--refresh", action="store_true",
                      help="re-download the named entries' files and overwrite their recorded values")
    args = parser.parse_args(argv)
    if args.refresh and not args.only:
        parser.error("--refresh needs --only ID [ID ...]: accept changed files one entry at a time")

    only = args.only
    if args.changed_from:
        from catalog.links import changed_entry_ids
        changed = changed_entry_ids(args.changed_from, args.entries)
        only = changed if only is None else [i for i in only if i in changed]
    results = record_checksums(args.entries, session=make_session(),
                               mode="check" if args.check else "refresh" if args.refresh else "fill", only=only)
    for r in results:
        if r.status != "ok":
            print(r.line())
    if args.check and any(r.status == "mismatch" for r in results):
        print("Update the sha256 and size shown above (or run catalog-checksums --refresh --only ID).",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
