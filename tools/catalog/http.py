"""Shared HTTP helpers: session factory and URL normalization."""

from __future__ import annotations

import os
from urllib.parse import quote, urlsplit, urlunsplit

import requests

from catalog import config

_SAFE = "/%:@!$&'()*+,;=-._~"


def make_session() -> requests.Session:
    """A session whose User-Agent is read from the environment at call time."""
    session = requests.Session()
    session.headers["User-Agent"] = os.environ.get("CATALOG_USER_AGENT") or config.USER_AGENT
    return session


def normalize_url(url: str) -> str:
    """Percent-encode unsafe path/query/fragment characters; idempotent."""
    parts = urlsplit(url)
    return urlunsplit((
        parts.scheme,
        parts.netloc,
        quote(parts.path, safe=_SAFE),
        quote(parts.query, safe=_SAFE + "?"),
        quote(parts.fragment, safe=_SAFE + "?"),
    ))
