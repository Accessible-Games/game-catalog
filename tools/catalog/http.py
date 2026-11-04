"""Shared HTTP helpers: session factory and URL normalization."""

from __future__ import annotations

import os
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

import requests

from catalog import config

_SAFE = "/%:@!$&'()*+,;=-._~"


class ForbiddenRedirect(requests.RequestException):
    """A redirect pointed at a forbidden download host and was not followed."""


def _refuse_forbidden_redirect(response: requests.Response, **_kwargs) -> requests.Response:
    """Response hook: runs on every hop, before requests follows the Location header.

    A response that is itself from a forbidden host (a caller that fetches one on purpose) may
    redirect within the forbidden hosts; any other response may not redirect into one.
    """
    location = response.headers.get("Location")
    if not response.is_redirect or not location:
        return response
    try:
        location = location.encode("latin1").decode("utf-8")
    except UnicodeError:
        pass
    target = urljoin(response.url, location)
    if config.is_forbidden_url(target) and not config.is_forbidden_url(response.url):
        response.close()
        raise ForbiddenRedirect(f"forbidden redirect to {target}", response=response)
    return response


def make_session() -> requests.Session:
    """A session whose User-Agent is read from the environment at call time.

    It refuses redirects into forbidden download hosts.
    """
    session = requests.Session()
    session.hooks["response"].append(_refuse_forbidden_redirect)
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
