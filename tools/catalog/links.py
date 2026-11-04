"""Link checker: verify every source URL still resolves."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import requests

from catalog.config import is_forbidden_url
from catalog.entries import ROOT, load_entries
from catalog.http import make_session, normalize_url

LinkStatus = Literal["ok", "forbidden", "dead", "error"]

MAX_WORKERS = 6
TIMEOUT = 20


@dataclass(frozen=True)
class LinkResult:
    url: str
    status: LinkStatus
    http_status: int | None
    size: int | None
    detail: str


@dataclass(frozen=True)
class SourceCheck:
    entry_id: str
    source: dict
    result: LinkResult
    size_changed: bool


def _size(response: requests.Response) -> int | None:
    headers = response.headers
    try:
        if response.status_code == 206:
            return int(headers["Content-Range"].rsplit("/", 1)[1])
        if response.status_code == 200 and "Content-Length" in headers:
            return int(headers["Content-Length"])
    except (KeyError, IndexError, ValueError):
        pass
    return None


def _classify(url: str, response: requests.Response) -> LinkResult:
    code = response.status_code
    if code in (200, 206):
        status: LinkStatus = "ok"
    elif code in (401, 403):
        status = "forbidden"
    elif code in (404, 410):
        status = "dead"
    else:
        status = "error"
    return LinkResult(url, status, code, _size(response), f"HTTP {code}")


def _ranged_get(url: str, session: requests.Session, timeout: float) -> requests.Response:
    return session.get(url, headers={"Range": "bytes=0-0"}, stream=True,
                       allow_redirects=True, timeout=timeout)


def check_url(url: str, session: requests.Session, timeout: float = TIMEOUT) -> LinkResult:
    target = normalize_url(url)
    try:
        try:
            response = session.head(target, allow_redirects=True, timeout=timeout)
            retry = response.status_code in (403, 405, 501)
        except requests.Timeout:
            raise
        except requests.ConnectionError:
            response, retry = None, True
        if retry:
            response = _ranged_get(target, session, timeout)
        try:
            return _classify(url, response)
        finally:
            response.close()
    except Exception as exc:  # noqa: BLE001 - any failure is reported, not raised
        return LinkResult(url, "error", None, None, type(exc).__name__)


def check_entries(
    entries: dict[str, dict],
    ids: Iterable[str] | None = None,
    *,
    session: requests.Session | None = None,
    workers: int = MAX_WORKERS,
) -> list[SourceCheck]:
    """Check every source of the selected entries (all entries if ids is None).

    Sources on a forbidden host are skipped without contacting it; catalog-validate rejects them.
    """
    session = session or make_session()
    selected = list(entries) if ids is None else [i for i in ids if i in entries]
    jobs = [
        (eid, source)
        for eid in selected
        for source in entries[eid].get("sources") or []
        if isinstance(source, dict) and isinstance(source.get("url"), str)
        and not is_forbidden_url(source["url"])
    ]

    def run(job: tuple[str, dict]) -> SourceCheck:
        eid, source = job
        result = check_url(source["url"], session)
        known = source.get("size")
        changed = known is not None and result.size is not None and known != result.size
        return SourceCheck(eid, source, result, changed)

    with ThreadPoolExecutor(max_workers=max(1, min(workers, MAX_WORKERS))) as pool:
        return list(pool.map(run, jobs))


def render_report(checks: list[SourceCheck], checked_at: str) -> str:
    sections = [
        ("Dead links", [c for c in checks if c.result.status == "dead"]),
        ("Unreachable / errors", [c for c in checks if c.result.status == "error"]),
        ("Forbidden (may be bot-blocking; check by hand)",
         [c for c in checks if c.result.status == "forbidden"]),
        ("Size changed", [c for c in checks if c.size_changed]),
    ]
    lines = ["# Link check", "", f"Checked at {checked_at}", ""]
    for title, items in sections:
        if not items:
            continue
        lines += [f"## {title}", ""]
        for c in items:
            what = c.result.detail
            if title == "Size changed":
                what = f"size {c.source.get('size')} -> {c.result.size}"
            lines.append(f"- {c.entry_id}: {c.source['url']} ({what})")
        lines.append("")

    def count(status: str) -> int:
        return sum(c.result.status == status for c in checks)

    lines.append(
        f"{len(checks)} checked: {count('ok')} ok, {count('forbidden')} forbidden, "
        f"{count('dead')} dead, {count('error')} errors, "
        f"{sum(c.size_changed for c in checks)} size changed."
    )
    return "\n".join(lines) + "\n"


def changed_entry_ids(base_ref: str, entries_dir: Path) -> list[str]:
    """Ids of entries added or modified since base_ref (deleted files ignored)."""
    entries_dir = Path(entries_dir).resolve()
    out = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=d", base_ref, "--", f"{entries_dir.name}/"],
        cwd=entries_dir.parent, check=True, capture_output=True, text=True,
    ).stdout
    return sorted(
        Path(line).stem for line in out.splitlines()
        if line.endswith(".json") and Path(line).parent.name == entries_dir.name
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="catalog-links", description="Check source URLs.")
    parser.add_argument("--entries", type=Path, default=ROOT / "entries")
    parser.add_argument("--only", nargs="+", metavar="ID")
    parser.add_argument("--changed-from", metavar="REF")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--fail-on-dead", action="store_true")
    args = parser.parse_args(argv)

    entries = load_entries(args.entries)
    ids = args.only
    if args.changed_from:
        changed = changed_entry_ids(args.changed_from, args.entries)
        ids = changed if ids is None else [i for i in ids if i in changed]
    checks = check_entries(entries, ids)
    report = render_report(checks, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8", newline="\n")
    print(report)
    if args.fail_on_dead and any(c.result.status in ("dead", "error") for c in checks):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
