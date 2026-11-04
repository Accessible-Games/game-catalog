from catalog.http import make_session, normalize_url


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
