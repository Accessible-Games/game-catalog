"""Shared constants for the catalog tooling."""

import os

REPO_URL = "https://github.com/olsonale/game-catalog"
INDEX_BASE = "https://catalog.accessiblegames.net/"
INDEX_DOMAIN = "catalog.accessiblegames.net"
MIRROR_BASE = "https://files.accessiblegames.net/"
FORBIDDEN_SOURCE_HOSTS = frozenset({"agarchive.net", "www.agarchive.net"})
USER_AGENT = os.environ.get(
    "CATALOG_USER_AGENT",
    "Mozilla/5.0 (compatible; game-catalog/0.1; +https://github.com/olsonale/game-catalog)",
)
