import pytest
import responses
import requests

from catalog.http import ForbiddenRedirect, make_session, normalize_url


def test_normalize_spaces():
    assert (
        normalize_url("https://example.com/files/ESP Pinball Demo 1.3.exe")
        == "https://example.com/files/ESP%20Pinball%20Demo%201.3.exe"
    )


def test_normalize_idempotent():
    once = normalize_url("https://Example.com/a b/ü?q=x y&r=1#frag")
    assert once == "https://Example.com/a%20b/%C3%BC?q=x%20y&r=1#frag"
    assert normalize_url(once) == once


def test_user_agent_env(monkeypatch):
    monkeypatch.setenv("CATALOG_USER_AGENT", "custom-agent/1")
    assert make_session().headers["User-Agent"] == "custom-agent/1"
    monkeypatch.delenv("CATALOG_USER_AGENT")
    assert "game-catalog" in make_session().headers["User-Agent"]


START = "https://example.com/start.zip"
BAD = "https://agarchive.net/x.7z"


@responses.activate
@pytest.mark.parametrize("location", [BAD, "https://www.agarchive.net/x.7z", "https://agarchive.net\\@evil.example/x.7z"])
def test_session_refuses_redirect_to_forbidden_host(location):
    responses.add(responses.GET, START, status=302, headers={"Location": location})
    with pytest.raises(ForbiddenRedirect) as exc:
        make_session().get(START, allow_redirects=True)
    assert "forbidden" in str(exc.value)
    assert [c.request.url for c in responses.calls] == [START]


@responses.activate
def test_session_refuses_later_hop_to_forbidden_host():
    responses.add(responses.GET, START, status=302, headers={"Location": "/second"})
    responses.add(responses.GET, "https://example.com/second", status=301, headers={"Location": BAD})
    with pytest.raises(requests.RequestException):
        make_session().get(START)
    assert all("agarchive" not in c.request.url for c in responses.calls)


@responses.activate
def test_session_follows_ordinary_redirects():
    responses.add(responses.GET, START, status=302, headers={"Location": "/real.zip"})
    responses.add(responses.GET, "https://example.com/real.zip", body="ok")
    assert make_session().get(START).text == "ok"


@responses.activate
def test_forbidden_start_may_redirect_within_forbidden_hosts():
    responses.add(responses.GET, BAD, status=302, headers={"Location": "https://www.agarchive.net/y.7z"})
    responses.add(responses.GET, "https://www.agarchive.net/y.7z", body="ok")
    assert make_session().get(BAD).text == "ok"
