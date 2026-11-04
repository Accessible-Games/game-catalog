import hashlib
import json

import pytest
import responses

from catalog.checksums import hash_url, main, record_checksums
from catalog.entries import load_entries, write_entry
from catalog.http import make_session
from catalog.validate import validate_entries

DATA = b"PK\x03\x04 a game"
SHA = hashlib.sha256(DATA).hexdigest()
URL = "https://dev.example/files/game.zip"
MIRROR = "https://files.accessiblegames.net/files/" + "a" * 64 + "/game.zip"


def dev(url=URL, **extra):
    return {"label": "Developer site", "url": url, "platform": "windows", "install": {"method": "zip"}, **extra}


def setup(tmp_path, *entries):
    d = tmp_path / "entries"
    d.mkdir()
    for e in entries:
        write_entry(d, e)
    return d


def game(id_="g", sources=None):
    return {"id": id_, "kind": "game", "title": "G", "sources": sources or [dev()]}


@responses.activate
def test_hash_url_streams_and_rejects_web_pages():
    responses.add(responses.GET, URL, body=DATA)
    responses.add(responses.GET, "https://dev.example/page", body=b"<!doctype html><p>hi", content_type="text/html")
    assert hash_url(make_session(), URL) == (SHA, len(DATA))
    with pytest.raises(Exception, match="web page"):
        hash_url(make_session(), "https://dev.example/page")


@responses.activate
def test_fill_records_missing_checksums_only(tmp_path):
    known = dev("https://dev.example/known.zip", sha256="b" * 64, size=5)
    d = setup(tmp_path, game("g"), game("k", [known]))
    responses.add(responses.GET, URL, body=DATA)
    results = record_checksums(d, session=make_session())
    assert [(r.entry_id, r.status) for r in results] == [("g", "recorded")]
    entries = load_entries(d)
    assert entries["g"]["sources"][0]["sha256"] == SHA and entries["g"]["sources"][0]["size"] == len(DATA)
    assert entries["k"]["sources"][0]["sha256"] == "b" * 64  # recorded values are not re-downloaded
    assert len(responses.calls) == 1
    assert validate_entries(entries) == []


@responses.activate
def test_mirror_web_and_url_sources_are_skipped(tmp_path):
    mirror = {"label": "Mirror", "url": MIRROR, "platform": "windows", "install": {"method": "zip"},
              "sha256": "a" * 64, "size": 1}
    web = {"label": "Play", "url": "https://dev.example/play", "platform": "web", "install": {"method": "none"}}
    page = {"label": "Page", "url": "https://dev.example/p", "platform": "windows", "install": {"method": "url"}}
    d = setup(tmp_path, game("g", [mirror, web, page]))
    assert record_checksums(d, session=make_session()) == []
    assert len(responses.calls) == 0


@responses.activate
def test_check_reports_mismatch_and_missing_without_writing(tmp_path):
    stale = dev(sha256="c" * 64, size=len(DATA))
    d = setup(tmp_path, game("s", [stale]), game("m", [dev("https://dev.example/m.zip")]))
    responses.add(responses.GET, URL, body=DATA)
    responses.add(responses.GET, "https://dev.example/m.zip", body=DATA)
    before = {p.name: p.read_bytes() for p in d.iterdir()}
    results = {r.entry_id: r for r in record_checksums(d, session=make_session(), mode="check")}
    assert results["s"].status == "mismatch" and SHA in results["s"].detail
    assert results["m"].status == "missing" and SHA in results["m"].detail
    assert {p.name: p.read_bytes() for p in d.iterdir()} == before


@responses.activate
def test_refresh_accepts_a_changed_file(tmp_path):
    d = setup(tmp_path, game("g", [dev(sha256="c" * 64, size=3)]))
    responses.add(responses.GET, URL, body=DATA)
    [r] = record_checksums(d, session=make_session(), mode="refresh", only=["g"])
    assert r.status == "updated"
    src = load_entries(d)["g"]["sources"][0]
    assert (src["sha256"], src["size"]) == (SHA, len(DATA))


@responses.activate
def test_download_errors_are_reported_not_recorded(tmp_path):
    d = setup(tmp_path, game())
    responses.add(responses.GET, URL, status=404)
    [r] = record_checksums(d, session=make_session())
    assert r.status == "error"
    assert "sha256" not in load_entries(d)["g"]["sources"][0]


@responses.activate
def test_same_url_is_downloaded_once(tmp_path):
    d = setup(tmp_path, game("a"), game("b"))
    responses.add(responses.GET, URL, body=DATA)
    record_checksums(d, session=make_session())
    assert len(responses.calls) == 1
    assert {e["sources"][0]["sha256"] for e in load_entries(d).values()} == {SHA}


@responses.activate
def test_cli_check_fails_only_on_mismatch(tmp_path, capsys):
    d = setup(tmp_path, game("m", [dev("https://dev.example/m.zip")]))
    responses.add(responses.GET, "https://dev.example/m.zip", body=DATA)
    assert main(["--entries", str(d), "--check"]) == 0
    stale = json.loads((d / "m.json").read_text(encoding="utf-8"))
    stale["sources"][0].update(sha256="c" * 64, size=1)
    (d / "m.json").write_text(json.dumps(stale), encoding="utf-8")
    assert main(["--entries", str(d), "--check"]) == 1
    out = capsys.readouterr().out
    assert "m:" in out and SHA in out


def test_cli_refresh_needs_named_entries(tmp_path):
    with pytest.raises(SystemExit):
        main(["--entries", str(tmp_path), "--refresh"])
