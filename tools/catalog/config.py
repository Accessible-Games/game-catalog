"""Shared constants for the catalog tooling."""

import os
from urllib.parse import urlsplit

from urllib3.exceptions import LocationParseError
from urllib3.util import parse_url

REPO_URL = "https://github.com/Accessible-Games/game-catalog"
INDEX_BASE = "https://catalog.accessiblegames.net/"
MIRROR_BASE = "https://files.accessiblegames.net/"
MIRROR_BUCKET = os.environ.get("R2_BUCKET", "accessiblegames-files")
FORBIDDEN_SOURCE_HOSTS = frozenset({"agarchive.net", "www.agarchive.net"})
USER_AGENT = os.environ.get(
    "CATALOG_USER_AGENT",
    "Mozilla/5.0 (compatible; game-catalog/0.1; +https://github.com/Accessible-Games/game-catalog)",
)


def _forbidden_host(host: str) -> bool:
    host = host.lower().rstrip(".")
    return any(host == h or host.endswith("." + h) for h in FORBIDDEN_SOURCE_HOSTS)


def is_forbidden_url(url: str) -> bool:
    """True if url's host is a forbidden download host or a subdomain of one.

    urlsplit and urllib3 (used by requests) disagree on some malformed URLs, such as a backslash
    in the netloc, so the URL is forbidden if EITHER parser says so. A URL that cannot be parsed
    fails closed.
    """
    try:
        hosts = [urlsplit(url).hostname or "", parse_url(url).host or ""]
    except (ValueError, LocationParseError):
        return True
    return any(_forbidden_host(h) for h in hosts)
