import pytest
import requests
import responses

from catalog.files import (
    NotAFileError, content_disposition_filename, looks_like_html, reject_html, response_filename,
    sniff, with_sniffed_extension,
)

ZIP = b"PK\x03\x04rest"
SEVEN = b"7z\xbc\xaf\x27\x1crest"
RAR = b"Rar!\x1a\x07\x00rest"
CAB = b"MSCFrest"
OLE = bytes.fromhex("D0CF11E0A1B11AE1") + b"rest"
MZ = b"MZ\x90\x00rest"


@pytest.mark.parametrize("head,kind", [
    (ZIP, "zip"), (SEVEN, "7z"), (RAR, "rar"), (CAB, "cab"), (OLE, "ole"), (MZ, "mz"),
    (b"<!DOCTYPE html><html>", "html"), (b"  \r\n\t<HTML lang=en>", "html"),
    (b"\xef\xbb\xbf<!doctype html>", "html"), (b"ID3\x03mp3", None), (b"", None), (b"M", None),
])
def test_sniff(head, kind):
    assert sniff(head) == kind


def test_looks_like_html():
    assert looks_like_html(b"\n  <!doctype html>")
    assert looks_like_html(b"<Html>")
    assert not looks_like_html(b"hello <html>")
    assert not looks_like_html(ZIP)


def test_reject_html():
    with pytest.raises(NotAFileError):
        reject_html("text/html; charset=utf-8", b"plain text", "https://x.test/a.php")
    with pytest.raises(NotAFileError):
        reject_html("application/octet-stream", b" <!DOCTYPE html>", "https://x.test/a.exe")
    with pytest.raises(NotAFileError):
        reject_html(None, b"<html><body>", "https://x.test/a.exe")
    reject_html("application/zip", ZIP, "https://x.test/a.zip")
    reject_html(None, b"", "https://x.test/a.zip")
    # a real archive is kept even when a misconfigured server calls it text/html
    reject_html("text/html", ZIP, "https://x.test/a.zip")


@pytest.mark.parametrize("value,name", [
    ('attachment; filename="Big Pig.exe"', "Big Pig.exe"),
    ("attachment; filename=game.zip", "game.zip"),
    ("attachment; filename*=UTF-8''%E3%83%91%E3%83%83%E3%82%AF.7z", "パック.7z"),
    ('attachment; filename="../../evil.exe"', "evil.exe"),
    ('attachment; filename="..\\x.exe"', "x.exe"),
    ('attachment; filename=".."', None),
    ("inline", None),
    (None, None),
    ("", None),
])
def test_content_disposition_filename(value, name):
    assert content_disposition_filename(value) == name


def test_with_sniffed_extension():
    assert with_sniffed_extension("download.php", MZ) == "download.exe"
    assert with_sniffed_extension("downloadBigPig.php", ZIP) == "downloadBigPig.zip"
    assert with_sniffed_extension("dl", SEVEN) == "dl.7z"
    assert with_sniffed_extension("click.php", OLE) == "click.msi"
    assert with_sniffed_extension("game.exe", ZIP) == "game.exe"  # a real extension is kept
    assert with_sniffed_extension("download.php", b"???") == "download.php"


def _get(url, **kw):
    session = requests.Session()
    return session.get(url, stream=True, **kw)


@responses.activate
def test_response_filename_precedence():
    responses.add(responses.GET, "https://a.test/download.php", body=MZ,
                  headers={"Content-Disposition": 'attachment; filename="Marina Break.exe"'})
    with _get("https://a.test/download.php") as r:
        assert response_filename(r, MZ) == "Marina Break.exe"

    responses.add(responses.GET, "https://a.test/click.php", status=302,
                  headers={"Location": "https://cdn.a.test/files/Music%20Puzzle.zip"})
    responses.add(responses.GET, "https://cdn.a.test/files/Music%20Puzzle.zip", body=ZIP)
    with _get("https://a.test/click.php") as r:
        assert response_filename(r, ZIP) == "Music Puzzle.zip"

    responses.add(responses.GET, "https://a.test/downloads/downloadBigPig.php", body=MZ)
    with _get("https://a.test/downloads/downloadBigPig.php") as r:
        assert response_filename(r, MZ) == "downloadBigPig.exe"

    responses.add(responses.GET, "https://a.test/", body=ZIP)
    with _get("https://a.test/") as r:
        assert response_filename(r, ZIP) == "download.zip"
