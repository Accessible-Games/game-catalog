"""Validate catalog entries: JSON Schema plus cross-entry rules."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import jsonschema

from catalog.config import MIRROR_BASE, is_forbidden_url
from catalog.entries import ROOT, EntryLoadError, load_entries, load_schema
from catalog.http import normalize_url
from catalog.mirror import is_mirror_url

_MIRROR_PATH = re.compile(r"files/([0-9a-f]{64})/[^/]+")


@dataclass(frozen=True)
class Problem:
    entry_id: str | None
    message: str


def _is_web_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
        return parts.scheme.lower() in ("http", "https") and bool(parts.hostname)
    except ValueError:
        return False


def _check_links(key: str, entry: dict, out: list[Problem]) -> None:
    links = entry.get("links")
    if not isinstance(links, dict):
        return
    for name, value in links.items():
        if isinstance(value, str) and not _is_web_url(value):
            out.append(Problem(key, f"links.{name}: URL must be http or https with a host ({value})"))


def _check_sources(key: str, entry: dict, out: list[Problem]) -> None:
    for i, source in enumerate(entry.get("sources") or []):
        if not isinstance(source, dict):
            continue
        where = f"sources[{i}]"
        url = source.get("url")
        if isinstance(url, str):
            if not _is_web_url(url):
                out.append(Problem(key, f"{where}: URL must be http or https with a host ({url})"))
            elif normalize_url(url) != url:
                out.append(Problem(key, f"{where}: URL must be percent-encoded: use {normalize_url(url)}"))
            if is_forbidden_url(url):
                out.append(Problem(key, f"{where}: agarchive download URLs are forbidden ({url})"))
            if is_mirror_url(url):
                if "sha256" not in source:
                    out.append(Problem(key, f"{where}: mirror source requires sha256"))
                if "size" not in source:
                    out.append(Problem(key, f"{where}: mirror source requires size"))
                parts = urlsplit(url)
                rest = urlunsplit(("", "", parts.path, parts.query, parts.fragment))
                match = _MIRROR_PATH.fullmatch(rest[len(urlsplit(MIRROR_BASE).path):])
                if not match:
                    out.append(Problem(key, f"{where}: mirror URL must look like files/<sha256>/<filename>"))
                elif source.get("sha256") is not None and match.group(1) != source["sha256"]:
                    out.append(Problem(key, f"{where}: mirror URL hash does not match sha256"))
        install = source.get("install")
        if isinstance(install, dict) and "installer" in install and install.get("method") != "installer":
            out.append(Problem(key, f"{where}: installer block is only allowed when install method is 'installer'"))


def _find_cycles(entries: dict[str, dict]) -> list[list[str]]:
    """DFS three-colour marking; returns one path per back edge found."""
    WHITE, GREY, BLACK = 0, 1, 2
    color = {k: WHITE for k in entries}
    cycles: list[list[str]] = []

    def deps(k: str) -> list[str]:
        d = entries[k].get("dependencies")
        return [x for x in d if isinstance(x, str) and x in entries] if isinstance(d, list) else []

    def visit(k: str, stack: list[str]) -> None:
        color[k] = GREY
        stack.append(k)
        for d in deps(k):
            if color[d] == GREY:
                cycles.append(stack[stack.index(d):] + [d])
            elif color[d] == WHITE:
                visit(d, stack)
        stack.pop()
        color[k] = BLACK

    for k in entries:
        if color[k] == WHITE:
            visit(k, [])
    return cycles


def validate_entries(entries: dict[str, dict]) -> list[Problem]:
    problems: list[Problem] = []
    validator = jsonschema.Draft202012Validator(load_schema())

    for key, entry in entries.items():
        for err in validator.iter_errors(entry):
            path = "/".join(str(p) for p in err.absolute_path) or "(root)"
            problems.append(Problem(key, f"schema: {path}: {err.message}"))
        if not isinstance(entry, dict):
            continue

        if entry.get("id") != key:
            problems.append(Problem(key, f"id {entry.get('id')!r} does not match filename {key}.json"))

        kind = entry.get("kind")
        for dep in entry.get("dependencies") or []:
            if dep not in entries:
                problems.append(Problem(key, f"unknown dependency {dep!r}"))

        extends = entry.get("extends")
        if extends is not None and extends not in entries:
            problems.append(Problem(key, f"extends unknown entry {extends!r}"))
        if kind == "extra" and extends is None:
            problems.append(Problem(key, "extra entries must set extends"))
        if extends is not None and kind not in ("extra", "access-mod"):
            problems.append(Problem(key, "extends is only allowed on extra or access-mod entries"))
        if entry.get("required") is not None and kind != "extra":
            problems.append(Problem(key, "required is only allowed on extra entries"))
        if "registration" in (entry.get("flags") or []) and not entry.get("approval"):
            problems.append(Problem(key, "registration flag requires an approval note"))

        install_into = entry.get("install_into")
        if install_into is not None and install_into not in entries:
            problems.append(Problem(key, f"install_into unknown entry {install_into!r}"))

        _check_sources(key, entry, problems)
        _check_links(key, entry, problems)

    valid = {k: v for k, v in entries.items() if isinstance(v, dict)}
    for cycle in _find_cycles(valid):
        problems.append(Problem(cycle[0], "dependency cycle: " + " -> ".join(cycle)))
    return problems


def validate_catalog(entries_dir: Path) -> list[Problem]:
    try:
        entries = load_entries(entries_dir)
    except EntryLoadError as exc:
        return [Problem(exc.path.stem, f"cannot load entry: {exc}")]
    return validate_entries(entries)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="catalog-validate", description="Validate catalog entries.")
    parser.add_argument("--entries", type=Path, default=ROOT / "entries")
    args = parser.parse_args(argv)
    problems = validate_catalog(args.entries)
    for p in problems:
        print(f"{p.entry_id}: {p.message}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
