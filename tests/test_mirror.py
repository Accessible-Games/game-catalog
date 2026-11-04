import json

import pytest
import responses

from catalog.config import MIRROR_BASE
from catalog.entries import load_entries, write_entry
from catalog.http import make_session
from catalog.mirror import (
    MemoryUploader,
    Mirrored,
    R2Uploader,
    hash_file,
    is_mirror_url,
    main,
    make_mirror_source,
    mirror_entries,
    mirror_file,
    mirror_key,
    mirror_url,
    safe_filename,
    unmirrored_source_indexes,
)
from catalog.validate import validate_entries

DATA = b"hello game"
URL = "https://example.com/files/My%20Game.zip"


def dev_source(**extra):
    s = {"label": "Dev", "url": URL, "platform": "windows", "install": {"method": "zip"}}
    s.update(extra)
    return s


def make_entry(id_="g", sources=None):
    return {"id": id_, "kind": "game", "title": "G", "sources": sources or [dev_source()]}


def test_safe_filename():
    assert safe_filename("ESP Pinball Demo 1.3.exe") == "ESP_Pinball_Demo_1.3.exe"
    assert safe_filename("パック.7z") == "file.7z"
    assert safe_filename("a%20b.zip") == "a_b.zip"
    assert safe_filename("a  --  b.zip") == "a_--_b.zip"
    assert safe_filename("..") == "file"


def test_mirror_key_and_url():
    key = mirror_key("ab" * 32, "x.zip")
    assert key == f"files/{'ab' * 32}/x.zip"
    assert mirror_url(key) == f"https://files.accessiblegames.net/files/{'ab' * 32}/x.zip"
    assert is_mirror_url(mirror_url(key))
    assert not is_mirror_url("https://example.com/x.zip")


def test_hash_file(tmp_path):
    p = tmp_path / "f"
    p.write_bytes(DATA)
    import hashlib

    assert hash_file(p) == (hashlib.sha256(DATA).hexdigest(), len(DATA))


def test_mirror_file_uploads_once(tmp_path):
    p = tmp_path / "f.zip"
    p.write_bytes(DATA)
    up = MemoryUploader()
    a = mirror_file(p, "f.zip", up)
    b = mirror_file(p, "f.zip", up)
    assert a == b
    assert len(up.objects) == 1
    assert list(up.objects.values()) == [DATA]
    assert a.url == MIRROR_BASE + mirror_key(a.sha256, "f.zip")


def test_make_mirror_source():
    m = Mirrored(url=MIRROR_BASE + "files/" + "a" * 64 + "/x.zip", sha256="a" * 64, size=3)
    src = make_mirror_source(dev_source(steps=[{"action": "run"}]), m)
    assert src["label"] == "Mirror"
    assert src["url"] == m.url and src["sha256"] == m.sha256 and src["size"] == 3
    assert src["platform"] == "windows" and src["install"] == {"method": "zip"}
    assert src["steps"] == [{"action": "run"}]


def test_unmirrored_indexes():
    assert unmirrored_source_indexes(make_entry()) == [0]
    m = Mirrored(url=MIRROR_BASE + "files/" + "a" * 64 + "/x.zip", sha256="a" * 64, size=3)
    e = make_entry(sources=[dev_source(sha256="a" * 64), make_mirror_source(dev_source(), m)])
    assert unmirrored_source_indexes(e) == []
    e = make_entry(sources=[dev_source(sha256="b" * 64), make_mirror_source(dev_source(), m)])
    assert unmirrored_source_indexes(e) == [0]


def setup_entries(tmp_path):
    d = tmp_path / "entries"
    d.mkdir()
    write_entry(d, make_entry())
    return d


@responses.activate
def test_mirror_entries_inserts_after_original(tmp_path):
    d = setup_entries(tmp_path)
    responses.add(responses.GET, URL, body=DATA)
    up = MemoryUploader()
    changed = mirror_entries(d, uploader=up, session=make_session(), download_dir=tmp_path / "dl")
    assert changed == ["g"]
    # downloaded under the unquoted basename
    assert (tmp_path / "dl" / "My_Game.zip").exists()
    entries = load_entries(d)
    src = entries["g"]["sources"]
    assert [s["label"] for s in src] == ["Dev", "Mirror"]
    assert src[0]["sha256"] == src[1]["sha256"] and src[0]["size"] == src[1]["size"] == len(DATA)
    assert src[1]["url"].endswith("/My_Game.zip")
    assert len(up.objects) == 1
    assert validate_entries(entries) == []


@responses.activate
def test_mirror_entries_idempotent(tmp_path):
    d = setup_entries(tmp_path)
    responses.add(responses.GET, URL, body=DATA)
    up = MemoryUploader()
    kw = dict(uploader=up, session=make_session(), download_dir=tmp_path / "dl")
    assert mirror_entries(d, **kw) == ["g"]
    before = (d / "g.json").read_text(encoding="utf-8")
    responses.calls.reset()
    assert mirror_entries(d, **kw) == []
    assert len(responses.calls) == 0
    assert (d / "g.json").read_text(encoding="utf-8") == before


@responses.activate
def test_mirror_entries_download_failure(tmp_path, capsys):
    d = setup_entries(tmp_path)
    before = (d / "g.json").read_text(encoding="utf-8")
    responses.add(responses.GET, URL, status=404)
    up = MemoryUploader()
    changed = mirror_entries(d, uploader=up, session=make_session(), download_dir=tmp_path / "dl")
    assert changed == []
    assert (d / "g.json").read_text(encoding="utf-8") == before
    assert up.objects == {}
    assert capsys.readouterr().out.startswith("g: ")


@responses.activate
def test_mirror_entries_only_filter(tmp_path):
    d = setup_entries(tmp_path)
    write_entry(d, make_entry("h"))
    responses.add(responses.GET, URL, body=DATA)
    changed = mirror_entries(
        d, uploader=MemoryUploader(), session=make_session(), download_dir=tmp_path / "dl", only=["h"]
    )
    assert changed == ["h"]
    assert len(load_entries(d)["g"]["sources"]) == 1


@responses.activate
def test_main_dry_run_writes_nothing(tmp_path, capsys):
    d = setup_entries(tmp_path)
    before = (d / "g.json").read_text(encoding="utf-8")
    responses.add(responses.GET, URL, body=DATA)
    assert main(["--entries", str(d), "--dry-run", "--download-dir", str(tmp_path / "dl")]) == 0
    assert (d / "g.json").read_text(encoding="utf-8") == before
    assert "g" in capsys.readouterr().out


def test_r2_from_env_missing(monkeypatch):
    for k in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"):
        monkeypatch.setenv(k, "x")
    monkeypatch.delenv("R2_BUCKET")
    with pytest.raises(RuntimeError, match="R2_BUCKET"):
        R2Uploader.from_env()


@responses.activate
def test_web_and_url_sources_skipped(tmp_path):
    web = {"label": "Site", "url": "https://example.com/play", "platform": "web", "install": {"method": "none"}}
    url = {"label": "Page", "url": "https://example.com/page", "platform": "windows", "install": {"method": "url"}}
    for src in (web, url):
        assert unmirrored_source_indexes(make_entry(sources=[src])) == []
    d = tmp_path / "entries"
    d.mkdir()
    write_entry(d, make_entry(sources=[web, url]))
    assert mirror_entries(d, uploader=MemoryUploader(), session=make_session(), download_dir=tmp_path / "dl") == []
    assert len(responses.calls) == 0


@responses.activate
def test_download_name_cannot_escape_download_dir(tmp_path):
    for n, tail in enumerate(["..%2F..%2Fevil.exe", "%5C..%5Cx.exe", "a%3Ab.exe"]):
        url = f"https://example.com/dl/{tail}"
        responses.add(responses.GET, url, body=DATA)
        d = tmp_path / f"entries{n}"
        d.mkdir()
        write_entry(d, make_entry(sources=[dev_source(url=url)]))
        dl = tmp_path / f"dl{n}" / "inner"
        assert mirror_entries(d, uploader=MemoryUploader(), session=make_session(), download_dir=dl) == ["g"]
        files = [p for p in tmp_path.rglob("*") if p.is_file() and p.suffix == ".exe"]
        assert files and all(dl in p.parents for p in files if f"dl{n}" in p.parts)
        assert not (tmp_path / f"dl{n}" / "evil.exe").exists()
        assert not (tmp_path / "evil.exe").exists()
