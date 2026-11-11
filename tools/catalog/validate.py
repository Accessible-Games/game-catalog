"""Validate catalog entries: JSON Schema plus cross-entry rules."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import date
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


# RFC 3986 authority: userinfo@host:port, i.e. unreserved, pct-encoded, sub-delims, ":", "@", "[", "]".
_AUTHORITY = re.compile(r"[A-Za-z0-9\-._~%!$&'()*+,;=:@\[\]]+")
# urlsplit silently drops tabs and newlines, so look for control characters before splitting.
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def _is_web_url(url: str) -> bool:
    if _CONTROL.search(url):
        return False
    try:
        parts = urlsplit(url)
        return (parts.scheme.lower() in ("http", "https") and bool(parts.hostname)
                and _AUTHORITY.fullmatch(parts.netloc) is not None)
    except ValueError:
        return False


def _check_links(key: str, entry: dict, out: list[Problem]) -> None:
    links = entry.get("links")
    if not isinstance(links, list):
        return
    seen: set[str] = set()
    for i, link in enumerate(links):
        value = link.get("url") if isinstance(link, dict) else None
        if not isinstance(value, str):
            continue
        if not _is_web_url(value):
            out.append(Problem(key, f"links[{i}]: URL must be http or https with a host ({value})"))
        if value in seen:
            out.append(Problem(key, f"links[{i}]: URL is listed more than once ({value})"))
        seen.add(value)


_DRIVE = re.compile(r"^[A-Za-z]:")


def _check_persist(key: str, entry: dict, out: list[Problem]) -> None:
    """Patterns the app treats as player data (Game Chooser engine/safety.py matches_persist).

    The app compares them lower-cased with backslashes turned into slashes, relative to the game's install folder,
    so anything that leaves that folder, or two patterns that compare equal, is refused.
    """
    persist = entry.get("persist")
    if persist is None:
        return
    if entry.get("kind") != "game":
        out.append(Problem(key, "persist is only allowed on game entries (the app reads it from the game, "
                                "and an extra's files are covered by its game's persist)"))
    if not isinstance(persist, list):
        return  # already a schema problem
    seen: dict[str, int] = {}
    for i, pattern in enumerate(persist):
        if not isinstance(pattern, str) or not pattern:
            continue  # already a schema problem
        norm = pattern.replace("\\", "/").lower()
        if norm.startswith("/") or _DRIVE.match(norm):
            out.append(Problem(key, f"persist[{i}]: {pattern!r} must be relative to the game's install folder, "
                                    "not an absolute path"))
        if ".." in norm.split("/"):
            out.append(Problem(key, f"persist[{i}]: {pattern!r} must not use .. to leave the game's install folder"))
        if norm in seen:
            j = seen[norm]
            out.append(Problem(key, f"persist[{i}]: {pattern!r} is the same as persist[{j}] ({persist[j]!r}); "
                                    "the app ignores case and treats \\ as /"))
        else:
            seen[norm] = i


_PRICED_MODELS_THAT_STOP_SELLING = ("free-to-try", "one-time", "subscription")


def _check_pricing(key: str, entry: dict, out: list[Problem]) -> None:
    pricing = entry.get("pricing")
    if not isinstance(pricing, dict):
        return
    model = pricing.get("model")
    if "price" in pricing and "currency" not in pricing:
        out.append(Problem(key, "pricing: price needs a currency"))
    if "currency" in pricing and "price" not in pricing:
        out.append(Problem(key, "pricing: currency is only used with a price"))
    if isinstance(model, str):  # a missing model is already a schema problem
        if "price" in pricing and model in ("free", "free-with-purchases"):
            out.append(Problem(key, f"pricing: price is not used with the {model} model"))
        if "suggested" in pricing and model != "pay-what-you-want":
            out.append(Problem(key, "pricing: suggested is only used with the pay-what-you-want model"))
        if model == "subscription" and "period" not in pricing:
            out.append(Problem(key, "pricing: period is required with the subscription model"))
        if "period" in pricing and model != "subscription":
            out.append(Problem(key, "pricing: period is only used with the subscription model"))
        if "no_longer_sold" in pricing and model not in _PRICED_MODELS_THAT_STOP_SELLING:
            out.append(Problem(key, "pricing: no_longer_sold is only used with the free-to-try, one-time "
                                    "or subscription model"))
    checked = pricing.get("checked")
    if isinstance(checked, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", checked):
        try:
            date.fromisoformat(checked)
        except ValueError:
            out.append(Problem(key, f"pricing.checked: not a real date ({checked})"))
    for name in ("url", "donate_url"):
        value = pricing.get(name)
        if isinstance(value, str) and not _is_web_url(value):
            out.append(Problem(key, f"pricing.{name}: URL must be http or https with a host ({value})"))


WINDOWS_LAUNCH_SUFFIXES = (".exe", ".bat", ".cmd", ".html", ".htm")


def _check_launch(key: str, entry: dict, out: list[Problem]) -> None:
    launch = entry.get("launch")
    windows = launch.get("windows") if isinstance(launch, dict) else None
    path = windows.get("path") if isinstance(windows, dict) else None
    if isinstance(path, str) and not path.lower().endswith(WINDOWS_LAUNCH_SUFFIXES):
        out.append(Problem(
            key, f"launch.windows.path {path!r} is not a file Game Chooser can start: "
                 "it must end in .exe, .bat, .cmd, .html or .htm"))


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
        if isinstance(extends, list):  # any other shape is already a schema problem
            for parent in dict.fromkeys(p for p in extends if isinstance(p, str)):
                if parent not in entries:
                    problems.append(Problem(key, f"extends unknown entry {parent!r}"))
                    continue
                parent_kind = entries[parent].get("kind") if isinstance(entries[parent], dict) else None
                if parent_kind != "game":
                    problems.append(Problem(
                        key, f"extends {parent!r}, which is not a game (its kind is {parent_kind!r}); "
                             "extends must name game entries"))
        if kind == "extra" and "extends" not in entry:
            problems.append(Problem(key, "extra entries must set extends"))
        if "extends" in entry and kind not in ("extra", "access-mod"):
            problems.append(Problem(key, "extends is only allowed on extra or access-mod entries"))
        if isinstance(extends, list) and len(set(p for p in extends if isinstance(p, str))) > 1:
            shared_steps = sorted({
                step.get("action") for source in entry.get("sources") or [] if isinstance(source, dict)
                for step in source.get("steps") or []
                if isinstance(step, dict) and step.get("action") in ("registry", "register")})
            if shared_steps:
                problems.append(Problem(
                    key, f"an extra that belongs to more than one game can't use {' or '.join(shared_steps)} steps: "
                         "uninstalling it from one game would undo them for the others"))
        if entry.get("required") is not None and kind != "extra":
            problems.append(Problem(key, "required is only allowed on extra entries"))

        _check_sources(key, entry, problems)
        _check_links(key, entry, problems)
        _check_persist(key, entry, problems)
        _check_launch(key, entry, problems)
        _check_pricing(key, entry, problems)

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
