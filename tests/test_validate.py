import copy
import json

from catalog.config import MIRROR_BASE
from catalog.entries import ROOT, load_entries
from catalog.validate import Problem, main, validate_catalog, validate_entries

SHA = "a" * 64


def make(id_, kind="game", **extra):
    entry = {
        "id": id_,
        "kind": kind,
        "title": id_.title(),
        "sources": [
            {
                "label": "Dev",
                "url": "https://example.com/x.zip",
                "platform": "windows",
                "install": {"method": "zip"},
            }
        ],
    }
    entry.update(extra)
    return entry


def catalog(*entries):
    return {e["id"]: e for e in entries}


def msgs(problems):
    return [p.message for p in problems]


def with_source(entry, **fields):
    entry = copy.deepcopy(entry)
    entry["sources"][0].update(fields)
    return entry


def test_valid_catalog_has_no_problems():
    assert validate_entries(load_entries(ROOT / "entries")) == []
    assert validate_catalog(ROOT / "entries") == []


def test_schema_error_reported():
    e = make("a")
    del e["title"]
    problems = validate_entries(catalog(e))
    assert any("title" in p.message and p.entry_id == "a" for p in problems)


def test_id_must_match_filename():
    problems = validate_entries({"a": make("b")})
    assert any("filename" in p.message for p in problems)


def test_unknown_dependency():
    problems = validate_entries(catalog(make("a", dependencies=["nope"])))
    assert any("nope" in p.message for p in problems)


def test_dependency_cycle():
    problems = validate_entries(
        catalog(make("a", dependencies=["b"]), make("b", dependencies=["a"]))
    )
    assert len(problems) == 1
    assert "cycle" in problems[0].message


def test_dependency_self_cycle():
    problems = validate_entries(catalog(make("a", dependencies=["a"])))
    assert len(problems) == 1 and "cycle" in problems[0].message


def test_extends_must_exist():
    problems = validate_entries(catalog(make("x", "extra", extends="nope")))
    assert any("extends" in p.message and "nope" in p.message for p in problems)


def test_extra_requires_extends():
    problems = validate_entries(catalog(make("x", "extra")))
    assert any("extends" in p.message for p in problems)


def test_extends_only_on_extra_or_access_mod():
    entries = catalog(make("g"), make("h", extends="g"))
    assert any("extends" in p.message for p in validate_entries(entries))
    ok = catalog(make("g"), make("m", "access-mod", extends="g"), make("x", "extra", extends="g"))
    assert validate_entries(ok) == []


def test_required_only_on_extras():
    assert any("required" in p.message for p in validate_entries(catalog(make("g", required=True))))
    ok = catalog(make("g"), make("x", "extra", extends="g", required=True))
    assert validate_entries(ok) == []


def test_registration_requires_approval():
    entries = catalog(make("g"), make("x", "extra", extends="g", flags=["registration"]))
    problems = validate_entries(entries)
    assert any("approval" in p.message for p in problems)


def test_registration_with_approval_ok():
    entries = catalog(
        make("g"),
        make("x", "extra", extends="g", flags=["registration"], approval={"note": "ok by dev"}),
    )
    assert validate_entries(entries) == []


def test_install_into_must_exist():
    problems = validate_entries(catalog(make("g"), make("x", "extra", extends="g", install_into="nope")))
    assert any("install_into" in p.message for p in problems)
    ok = catalog(make("g"), make("x", "extra", extends="g", install_into="g"))
    assert validate_entries(ok) == []


def test_installer_block_only_for_installer_method():
    bad = make("a")
    bad["sources"][0]["install"]["installer"] = {"type": "inno", "mode": "extract"}
    assert any("installer" in p.message for p in validate_entries(catalog(bad)))
    good = make("b")
    good["sources"][0]["install"] = {
        "method": "installer",
        "installer": {"type": "inno", "mode": "extract"},
    }
    assert validate_entries(catalog(good)) == []


def test_agarchive_source_rejected():
    for url in ("https://agarchive.net/games/x.7z", "https://www.agarchive.net/games/x.7z",
                "https://AGArchive.net/games/x.7z", "https://agarchive.net./games/x.7z",
                "https://files.agarchive.net/x.7z", "HTTPS://WWW.AGARCHIVE.NET./x.7z"):
        problems = validate_entries(catalog(with_source(make("a"), url=url)))
        assert any("agarchive" in p.message for p in problems), url


def test_agarchive_credit_link_allowed():
    e = make("a", links={"agarchive": "https://agarchive.net/games/x.html"})
    assert validate_entries(catalog(e)) == []


def test_mirror_source_requires_hash_and_size():
    url = f"{MIRROR_BASE}files/{SHA}/a.zip"
    problems = validate_entries(catalog(with_source(make("a"), url=url)))
    assert any("sha256" in p.message for p in problems)
    assert any("size" in p.message for p in problems)
    ok = with_source(make("a"), url=url, sha256=SHA, size=10)
    assert validate_entries(catalog(ok)) == []


def test_mirror_url_must_match_hash():
    url = f"{MIRROR_BASE}files/{'b' * 64}/a.zip"
    problems = validate_entries(catalog(with_source(make("a"), url=url, sha256=SHA, size=10)))
    assert any("mirror" in p.message for p in problems)


def test_mirror_url_bad_shape():
    url = f"{MIRROR_BASE}elsewhere/a.zip"
    problems = validate_entries(catalog(with_source(make("a"), url=url, sha256=SHA, size=10)))
    assert any("mirror" in p.message for p in problems)


def test_validate_catalog_reports_load_error(tmp_path):
    (tmp_path / "bad.json").write_text("{nope", encoding="utf-8")
    problems = validate_catalog(tmp_path)
    assert len(problems) == 1 and isinstance(problems[0], Problem)


def test_main_exit_codes(tmp_path, capsys):
    (tmp_path / "a.json").write_text(json.dumps(make("a")), encoding="utf-8")
    assert main(["--entries", str(tmp_path)]) == 0
    (tmp_path / "b.json").write_text(json.dumps(make("c")), encoding="utf-8")
    assert main(["--entries", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert out.startswith("b: ") and "filename" in out


def test_mirror_detection_ignores_host_case():
    url = f"https://FILES.AccessibleGames.net/files/{SHA}/a.zip"
    problems = validate_entries(catalog(with_source(make("a"), url=url)))
    assert any("sha256" in p.message for p in problems)
    bad = f"https://Files.accessiblegames.net/files/{'b' * 64}/a.zip"
    problems = validate_entries(catalog(with_source(make("a"), url=bad, sha256=SHA, size=1)))
    assert any("hash does not match" in p.message for p in problems)


def test_source_url_must_be_http_with_host():
    for url in ("ftp://example.com/x.zip", "example.com/x.zip", "https:///x.zip", "javascript:alert(1)",
                "file:///C:/x.zip", "https://[::1/x.zip"):
        problems = validate_entries(catalog(with_source(make("a"), url=url)))
        assert any("http or https" in p.message for p in problems), url


def test_source_url_must_be_percent_encoded():
    problems = validate_entries(catalog(with_source(make("a"), url="https://example.com/My Game 1.0.zip")))
    assert any("percent-encoded" in p.message and "My%20Game%201.0.zip" in p.message for p in problems)
    ok = with_source(make("a"), url="https://example.com/My%20Game%201.0.zip?a=1&b=%C3%A9")
    assert validate_entries(catalog(ok)) == []


def test_links_must_be_http_with_host():
    for value in ("mailto:dev@example.com", "/relative/page", "ftp://example.com/"):
        problems = validate_entries(catalog(make("a", links={"homepage": value})))
        assert any("links.homepage" in p.message and "http or https" in p.message for p in problems), value
    ok = make("a", links={"homepage": "http://example.com/a page"})
    assert validate_entries(catalog(ok)) == []
