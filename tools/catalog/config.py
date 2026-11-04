"""Shared constants for the catalog tooling."""

import os
from urllib.parse import urlsplit

REPO_URL = "https://github.com/Accessible-Games/game-catalog"
INDEX_BASE = "https://catalog.accessiblegames.net/"
INDEX_DOMAIN = "catalog.accessiblegames.net"
MIRROR_BASE = "https://files.accessiblegames.net/"
FORBIDDEN_SOURCE_HOSTS = frozenset({"agarchive.net", "www.agarchive.net"})
USER_AGENT = os.environ.get(
    "CATALOG_USER_AGENT",
    "Mozilla/5.0 (compatible; game-catalog/0.1; +https://github.com/Accessible-Games/game-catalog)",
)


def is_forbidden_url(url: str) -> bool:
    """True if url's host is a forbidden download host or a subdomain of one."""
    try:
        host = (urlsplit(url).hostname or "").rstrip(".")
    except ValueError:
        return False
    return any(host == h or host.endswith("." + h) for h in FORBIDDEN_SOURCE_HOSTS)
