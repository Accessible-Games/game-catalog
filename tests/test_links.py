import json
import subprocess

import pytest
import requests
import responses

from catalog import links
from catalog.links import LinkResult, SourceCheck, check_entries, check_url, render_report

URL = "https://example.com/game.zip"


@pytest.fixture
def session():
    return requests.Session()


@responses.activate
def test_ok_head(session):
    responses.add(responses.HEAD, URL, status=200, headers={"Content-Length": "123"})
    r = check_url(URL, session)
    assert (r.status, r.http_status, r.size) == ("ok", 200, 123)


@responses.activate
def test_head_405_falls_back_to_get(session):
    responses.add(responses.HEAD, URL, status=405)
    responses.add(responses.GET, URL, status=206, headers={"Content-Range": "bytes 0-0/999"}, body="x")
    r = check_url(URL, session)
    assert (r.status, r.http_status, r.size) == ("ok", 206, 999)
    assert responses.calls[1].request.headers["Range"] == "bytes=0-0"


@responses.activate
def test_connection_error_falls_back_to_get(session):
    responses.add(responses.HEAD, URL, body=requests.ConnectionError("reset"))
    responses.add(responses.GET, URL, status=200, headers={"Content-Length": "5"}, body="x")
    assert check_url(URL, session).status == "ok"


@responses.activate
def test_forbidden(session):
    responses.add(responses.HEAD, URL, status=403)
    responses.add(responses.GET, URL, status=403)
    r = check_url(URL, session)
    assert (r.status, r.http_status) == ("forbidden", 403)


@responses.activate
def test_unauthorized_is_forbidden(session):
    responses.add(responses.HEAD, URL, status=401)
    assert check_url(URL, session).status == "forbidden"


@responses.activate
@pytest.mark.parametrize("code", [404, 410])
def test_dead(session, code):
    responses.add(responses.HEAD, URL, status=code)
    r = check_url(URL, session)
    assert (r.status, r.http_status) == ("dead", code)


@responses.activate
def test_other_status_is_error(session):
    responses.add(responses.HEAD, URL, status=500)
    assert check_url(URL, session).status == "error"


@responses.activate
def test_timeout_is_error(session):
    responses.add(responses.HEAD, URL, body=requests.exceptions.ConnectTimeout())
    r = check_url(URL, session)
    assert (r.status, r.detail) == ("error", "ConnectTimeout")
    assert len(responses.calls) == 1


def _entry(eid, url, size=None):
    src = {"label": "x", "url": url}
    if size is not None:
        src["size"] = size
    return {"id": eid, "sources": [src]}


@responses.activate
def test_size_changed():
    responses.add(responses.HEAD, "https://a.test/a", status=200, headers={"Content-Length": "200"})
    responses.add(responses.HEAD, "https://a.test/b", status=200, headers={"Content-Length": "100"})
    responses.add(responses.HEAD, "https://a.test/c", status=200, headers={"Content-Length": "100"})
    entries = {
        "a": _entry("a", "https://a.test/a", 100),
        "b": _entry("b", "https://a.test/b", 100),
        "c": _entry("c", "https://a.test/c"),
    }
    checks = {c.entry_id: c for c in check_entries(entries, session=requests.Session())}
    assert checks["a"].size_changed is True
    assert checks["b"].size_changed is False
    assert checks["c"].size_changed is False


@responses.activate
def test_check_entries_ids_filter():
    responses.add(responses.HEAD, "https://a.test/a", status=200)
    entries = {"a": _entry("a", "https://a.test/a"), "b": _entry("b", "https://a.test/b")}
    checks = check_entries(entries, ["a", "missing"], session=requests.Session())
    assert [c.entry_id for c in checks] == ["a"]


def _check(eid, status, detail="", size_changed=False):
    res = LinkResult(f"https://x.test/{eid}", status, None, None, detail)
    return SourceCheck(eid, {"url": res.url}, res, size_changed)


def test_report_sections():
    text = render_report(
        [
            _check("d", "dead", "HTTP 404"),
            _check("e", "error", "ConnectTimeout"),
            _check("f", "forbidden", "HTTP 403"),
            _check("s", "ok", size_changed=True),
            _check("g", "ok"),
        ],
        "2026-11-03T00:00:00Z",
    )
    assert "## Dead links\n\n- d: https://x.test/d (HTTP 404)" in text
    assert "## Unreachable / errors\n\n- e: https://x.test/e (ConnectTimeout)" in text
    assert "## Forbidden (may be bot-blocking; check by hand)\n\n- f: https://x.test/f (HTTP 403)" in text
    assert "## Size changed\n\n- s: https://x.test/s" in text
    assert "2026-11-03T00:00:00Z" in text
    assert "5 checked" in text.splitlines()[-1] or "5 checked" in text


def _write(tmp_path, eid, url):
    d = tmp_path / "entries"
    d.mkdir(exist_ok=True)
    (d / f"{eid}.json").write_text(json.dumps(_entry(eid, url)), encoding="utf-8")
    return d


@responses.activate
def test_fail_on_dead_ignores_forbidden(tmp_path):
    responses.add(responses.HEAD, "https://a.test/f", status=403)
    responses.add(responses.GET, "https://a.test/f", status=403)
    d = _write(tmp_path, "f", "https://a.test/f")
    report = tmp_path / "links.md"
    assert links.main(["--entries", str(d), "--report", str(report), "--fail-on-dead"]) == 0
    assert "Forbidden" in report.read_text(encoding="utf-8")
    responses.add(responses.HEAD, "https://a.test/g", status=404)
    _write(tmp_path, "g", "https://a.test/g")
    assert links.main(["--entries", str(d), "--report", str(report), "--fail-on-dead"]) == 1
    assert links.main(["--entries", str(d), "--report", str(report)]) == 0


@responses.activate
def test_main_only(tmp_path):
    responses.add(responses.HEAD, "https://a.test/f", status=404)
    d = _write(tmp_path, "f", "https://a.test/f")
    _write(tmp_path, "g", "https://a.test/g")  # would error if contacted
    assert links.main(["--entries", str(d), "--only", "f", "--fail-on-dead"]) == 1


def test_changed_entry_ids(tmp_path):
    def git(*a):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a],
                       cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q", "-b", "main")
    d = tmp_path / "entries"
    d.mkdir()
    for n in ("keep", "mod", "gone"):
        (d / f"{n}.json").write_text("{}", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    (d / "mod.json").write_text('{"a": 1}', encoding="utf-8")
    (d / "gone.json").unlink()
    (d / "new.json").write_text("{}", encoding="utf-8")
    (d / "notes.txt").write_text("x", encoding="utf-8")
    git("add", "-A")
    assert links.changed_entry_ids("HEAD", d) == ["mod", "new"]
