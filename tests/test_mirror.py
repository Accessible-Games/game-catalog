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


@responses.activate
def test_forbidden_sources_never_fetched(tmp_path):
    bad = [dev_source(url=u) for u in ("https://agarchive.net./games/x.7z", "https://www.AGARCHIVE.net/g/y.zip",
                                         "https://files.agarchive.net/z.zip")]
    assert unmirrored_source_indexes(make_entry(sources=bad)) == []
    d = tmp_path / "entries"
    d.mkdir()
    write_entry(d, make_entry(sources=bad))
    assert mirror_entries(d, uploader=MemoryUploader(), session=make_session(), download_dir=tmp_path / "dl") == []
    assert len(responses.calls) == 0


def test_is_mirror_url_ignores_host_case():
    assert is_mirror_url("https://FILES.accessiblegames.net/files/x/y.zip")
    assert not is_mirror_url("https://files.accessiblegames.net.evil.test/files/x/y.zip")


def test_memory_uploader_find(tmp_path):
    p = tmp_path / "f.zip"
    p.write_bytes(DATA)
    up = MemoryUploader()
    sha = hash_file(p)[0]
    assert up.find(sha) is None
    up.upload(p, mirror_key(sha, "f.zip"))
    assert up.find(sha) == mirror_key(sha, "f.zip")
    assert up.find("0" * 64) is None


class FakeS3:
    def __init__(self, keys):
        self.keys = keys
        self.calls = []

    def list_objects_v2(self, **kw):
        self.calls.append(kw)
        found = [k for k in self.keys if k.startswith(kw["Prefix"])][: kw["MaxKeys"]]
        return {"KeyCount": len(found), **({"Contents": [{"Key": k} for k in found]} if found else {})}


def test_r2_uploader_find():
    sha = "c" * 64
    client = FakeS3([f"files/{sha}/Game.zip", f"files/{'d' * 64}/x.zip"])
    up = R2Uploader(client, "bucket")
    assert up.find(sha) == f"files/{sha}/Game.zip"
    assert client.calls == [{"Bucket": "bucket", "Prefix": f"files/{sha}/", "MaxKeys": 1}]
    assert up.find("e" * 64) is None


def test_same_bytes_stored_once_under_first_name(tmp_path):
    a, b = tmp_path / "a.zip", tmp_path / "b.zip"
    a.write_bytes(DATA)
    b.write_bytes(DATA)
    up = MemoryUploader()
    first = mirror_file(a, "Game v1.zip", up)
    second = mirror_file(b, "other-name.zip", up)
    assert second == first
    assert list(up.objects) == [mirror_key(first.sha256, "Game v1.zip")]


@responses.activate
def test_recorded_sha_mismatch_warns_and_skips(tmp_path, capsys):
    d = tmp_path / "entries"
    d.mkdir()
    write_entry(d, make_entry(sources=[dev_source(sha256="f" * 64, size=len(DATA))]))
    before = (d / "g.json").read_text(encoding="utf-8")
    responses.add(responses.GET, URL, body=DATA)
    up = MemoryUploader()
    assert mirror_entries(d, uploader=up, session=make_session(), download_dir=tmp_path / "dl") == []
    assert up.objects == {}
    assert (d / "g.json").read_text(encoding="utf-8") == before
    err = capsys.readouterr().err
    assert "g: " in err and "sha256" in err and "f" * 64 in err


@responses.activate
def test_php_download_gets_real_filename(tmp_path):
    php = "https://example.com/downloads/downloadBigPig.php"
    cd = "https://example.com/softs/download.php?download=4"
    redirect = "https://example.com/clicks/click.php?id=9"
    responses.add(responses.GET, php, body=b"MZ\x90\x00big pig")
    responses.add(responses.GET, cd, body=b"PK\x03\x04marina",
                  headers={"Content-Disposition": 'attachment; filename="Marina Break.zip"'})
    responses.add(responses.GET, redirect, status=302, headers={"Location": "https://cdn.example.com/Music%20Puzzle.7z"})
    responses.add(responses.GET, "https://cdn.example.com/Music%20Puzzle.7z", body=b"7z\xbc\xaf\x27\x1cmusic")
    d = tmp_path / "entries"
    d.mkdir()
    write_entry(d, make_entry(sources=[dev_source(url=u) for u in (php, cd, redirect)]))
    up = MemoryUploader()
    assert mirror_entries(d, uploader=up, session=make_session(), download_dir=tmp_path / "dl") == ["g"]
    names = sorted(k.rsplit("/", 1)[1] for k in up.objects)
    assert names == ["Marina_Break.zip", "Music_Puzzle.7z", "downloadBigPig.exe"]
    assert validate_entries(load_entries(d)) == []


@responses.activate
def test_html_response_is_not_mirrored(tmp_path, capsys):
    page = "https://example.com/audiogames/music-puzzle.php"
    typed = "https://example.com/files/game.exe"
    responses.add(responses.GET, page, body="\n  <!DOCTYPE html><html><body>Info</body></html>",
                  content_type="application/octet-stream")
    responses.add(responses.GET, typed, body="Please log in", content_type="text/html")
    d = tmp_path / "entries"
    d.mkdir()
    write_entry(d, make_entry(sources=[dev_source(url=page), dev_source(url=typed)]))
    before = (d / "g.json").read_text(encoding="utf-8")
    up = MemoryUploader()
    assert mirror_entries(d, uploader=up, session=make_session(), download_dir=tmp_path / "dl") == []
    assert up.objects == {}
    assert (d / "g.json").read_text(encoding="utf-8") == before
    assert capsys.readouterr().out.count("not a file") == 2
    assert not [p for p in (tmp_path / "dl").rglob("*") if p.is_file()]


@responses.activate
def test_redirect_to_forbidden_host_is_a_download_failure(tmp_path, capsys):
    d = setup_entries(tmp_path)
    before = (d / "g.json").read_text(encoding="utf-8")
    responses.add(responses.GET, URL, status=302, headers={"Location": "https://agarchive.net/x.7z"})
    up = MemoryUploader()
    assert mirror_entries(d, uploader=up, session=make_session(), download_dir=tmp_path / "dl") == []
    assert (d / "g.json").read_text(encoding="utf-8") == before
    assert up.objects == {}
    assert "forbidden redirect" in capsys.readouterr().out
    assert [c.request.url for c in responses.calls] == [URL]
