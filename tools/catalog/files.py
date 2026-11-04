"""Identify downloaded files by their first bytes and name them from the HTTP response.

Shared by catalog-mirror and the private importer.
"""

from __future__ import annotations

import re
from email.message import Message
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

HEAD_SIZE = 512

_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"PK\x03\x04", "zip"),
    (b"7z\xbc\xaf\x27\x1c", "7z"),
    (b"Rar!", "rar"),
    (b"MSCF", "cab"),
    (bytes.fromhex("D0CF11E0A1B11AE1"), "ole"),
    (b"MZ", "mz"),
)

KIND_EXTENSION = {"zip": ".zip", "7z": ".7z", "rar": ".rar", "cab": ".cab", "ole": ".msi", "mz": ".exe"}

# Extensions that name a server script or page rather than the file it sends.
_SCRIPT_EXTENSIONS = {"", ".php", ".asp", ".aspx", ".jsp", ".cgi", ".pl", ".py", ".htm", ".html", ".do"}


class NotAFileError(ValueError):
    """The response is a web page, not a downloadable file."""


def looks_like_html(head: bytes) -> bool:
    text = head.removeprefix(b"\xef\xbb\xbf").lstrip().lower()
    return text.startswith((b"<!doctype", b"<html"))


def sniff(head: bytes) -> str | None:
    """'zip', '7z', 'rar', 'cab', 'ole', 'mz', 'html', or None when unknown."""
    for magic, kind in _MAGIC:
        if head.startswith(magic):
            return kind
    return "html" if looks_like_html(head) else None


def read_head(path: Path) -> bytes:
    with Path(path).open("rb") as f:
        return f.read(HEAD_SIZE)


def reject_html(content_type: str | None, head: bytes, url: str) -> None:
    """Raise NotAFileError for a web page: an HTML body, or text/html that isn't a known archive."""
    kind = sniff(head)
    is_html_type = (content_type or "").split(";")[0].strip().lower() == "text/html"
    if kind == "html" or (is_html_type and kind not in KIND_EXTENSION):
        raise NotAFileError(f"not a file (got a web page): {url}")


def _last_component(name: str | None) -> str | None:
    if not name:
        return None
    name = re.split(r"[/\\]", name)[-1].strip()
    return None if name in ("", ".", "..") or "\0" in name else name


def content_disposition_filename(value: str | None) -> str | None:
    if not value:
        return None
    msg = Message()
    msg["content-disposition"] = value
    return _last_component(msg.get_filename())


def with_sniffed_extension(name: str, head: bytes) -> str:
    """Swap a script-like or missing extension (download.php) for the one the bytes show."""
    path = PurePosixPath(name)
    ext = KIND_EXTENSION.get(sniff(head) or "")
    if ext and path.suffix.lower() in _SCRIPT_EXTENSIONS:
        return path.stem + ext if path.suffix else name + ext
    return name


def response_filename(response, head: bytes) -> str:
    """Content-Disposition filename, else the final URL's basename, with a sniffed extension if needed."""
    name = content_disposition_filename(response.headers.get("Content-Disposition"))
    if name is None:
        name = _last_component(unquote(urlsplit(response.url).path)) or "download"
    return with_sniffed_extension(name, head)
