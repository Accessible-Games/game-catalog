import pytest

from catalog.config import is_forbidden_url


@pytest.mark.parametrize("url", [
    "https://agarchive.net/games/x.7z",
    "https://www.agarchive.net/games/x.7z",
    "https://agarchive.net./games/x.7z",
    "https://www.agarchive.net./games/x.7z",
    "https://AGArchive.NET/games/x.7z",
    "https://files.agarchive.net/x.7z",
    "https://cdn.www.agarchive.net/x.7z",
    "http://agarchive.net:8080/x.7z",
    "https://user@agarchive.net/x.7z",
])
def test_forbidden(url):
    assert is_forbidden_url(url)


@pytest.mark.parametrize("url", [
    "https://example.com/agarchive.net/x.7z",
    "https://notagarchive.net/x.7z",
    "https://agarchive.net.example.com/x.7z",
    "https://files.accessiblegames.net/files/x.7z",
    "not a url",
    "",
    "http://[::1/",
])
def test_allowed(url):
    assert not is_forbidden_url(url)
