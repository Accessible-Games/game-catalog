import gzip
import hashlib
import json

import jsonschema
import pytest
from referencing import Registry, Resource

from catalog.entries import ROOT
from catalog.index import SCHEMA_VERSION, build_index, main, write_index
from catalog.validate import validate_entries

NOW = "2026-01-01T00:00:00Z"


def make(id_, kind="game", **extra):
    entry = {
        "id": id_,
        "kind": kind,
        "title": id_.title(),
        "sources": [
            {"label": "Dev", "url": "https://example.com/x.zip", "platform": "windows",
             "install": {"method": "zip"}}
        ],
    }
    entry.update(extra)
    return entry


def catalog(*entries):
    return {e["id"]: e for e in entries}


def test_entries_sorted_and_complete():
    index = build_index(catalog(make("zeta"), make("alpha"), make("mid")), NOW)
    assert index["schema_version"] == SCHEMA_VERSION == 2
    assert index["generated_at"] == NOW
    assert [e["id"] for e in index["entries"]] == ["alpha", "mid", "zeta"]


def test_extras_derived():
    entries = catalog(
        make("g"),
        make("e2", kind="extra", extends=["g"]),
        make("e1", kind="extra", extends=["g"], required=True),
    )
    by_id = {e["id"]: e for e in build_index(entries, NOW)["entries"]}
    assert by_id["g"]["extras"] == [{"id": "e1", "required": True}, {"id": "e2", "required": False}]
    assert by_id["e1"]["extras"] == []
    assert "extras" not in entries["g"]


def test_extra_with_two_games_listed_under_both():
    entries = catalog(
        make("g"),
        make("h"),
        make("other"),
        make("patch", kind="extra", extends=["h", "g"], required=True),
        make("addon", kind="extra", extends=["g"]),
    )
    assert validate_entries(entries) == []
    index = build_index(entries, NOW)
    _index_validator().validate(index)
    by_id = {e["id"]: e for e in index["entries"]}
    assert by_id["g"]["extras"] == [{"id": "addon", "required": False}, {"id": "patch", "required": True}]
    assert by_id["h"]["extras"] == [{"id": "patch", "required": True}]
    assert by_id["other"]["extras"] == []
    assert by_id["patch"]["extends"] == ["h", "g"]


def test_deterministic_bytes(tmp_path):
    entries = catalog(make("b"), make("a"))
    a = write_index(build_index(entries, NOW), tmp_path / "a")[0].read_bytes()
    b = write_index(build_index(entries, NOW), tmp_path / "b")[0].read_bytes()
    assert a == b


def test_meta_hash_matches(tmp_path):
    index = build_index(catalog(make("a")), NOW)
    gz, meta = write_index(index, tmp_path)
    assert gz.name == "index.json.gz" and meta.name == "index-meta.json"
    m = json.loads(meta.read_text(encoding="utf-8"))
    assert m == {
        "schema_version": 2,
        "generated_at": NOW,
        "entry_count": 1,
        "sha256": hashlib.sha256(gz.read_bytes()).hexdigest(),
        "index_url": "index.json.gz",
    }
    assert json.loads(gzip.decompress(gz.read_bytes())) == index


def test_headers_written(tmp_path):
    # Workers static assets read _headers: the index is gzip bytes that clients unpack themselves,
    # and the small meta file is cheap to re-check, so it is cached only briefly.
    write_index(build_index(catalog(make("a")), NOW), tmp_path)
    rules = (tmp_path / "_headers").read_text(encoding="utf-8")
    assert "/index.json.gz\n  Content-Type: application/gzip\n" in rules
    assert "/index-meta.json\n" in rules and "max-age=60" in rules
    assert "Access-Control-Allow-Origin: *" in rules
    assert not (tmp_path / "CNAME").exists()


def _index_validator():
    entry_schema = json.loads((ROOT / "schema" / "entry.schema.json").read_text(encoding="utf-8"))
    index_schema = json.loads((ROOT / "schema" / "index.schema.json").read_text(encoding="utf-8"))
    registry = Registry().with_resources([
        ("entry.schema.json", Resource.from_contents(entry_schema)),
        (entry_schema["$id"], Resource.from_contents(entry_schema)),
    ])
    return jsonschema.Draft202012Validator(index_schema, registry=registry)


def test_index_validates_against_index_schema():
    entries = catalog(make("g"), make("e1", kind="extra", extends=["g"], required=True))
    index = build_index(entries, NOW)
    validator = _index_validator()
    validator.validate(index)
    bad = json.loads(json.dumps(index))
    bad["entries"][0]["colour"] = "red"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(bad)


def test_persist_carried_into_the_index():
    entries = catalog(make("g", persist=["Saves/", "*.sav"]), make("h", persist=[]), make("k"))
    index = build_index(entries, NOW)
    _index_validator().validate(index)
    by_id = {e["id"]: e for e in index["entries"]}
    assert by_id["g"]["persist"] == ["Saves/", "*.sav"]
    assert by_id["h"]["persist"] == []  # checked, nothing to keep: kept apart from "not checked"
    assert "persist" not in by_id["k"]


def test_real_entries_validate_against_index_schema():
    from catalog.entries import load_entries
    _index_validator().validate(build_index(load_entries(ROOT / "entries"), NOW))


def test_main_refuses_invalid(tmp_path):
    entries = tmp_path / "entries"
    entries.mkdir()
    (entries / "bad.json").write_text(json.dumps({"id": "bad"}), encoding="utf-8")
    out = tmp_path / "out"
    assert main(["--entries", str(entries), "--out", str(out), "--generated-at", NOW]) == 1
    assert not out.exists()


def test_main_writes_three_files(tmp_path):
    entries = tmp_path / "entries"
    entries.mkdir()
    (entries / "a.json").write_text(json.dumps(make("a")), encoding="utf-8")
    out = tmp_path / "out"
    assert main(["--entries", str(entries), "--out", str(out), "--generated-at", NOW]) == 0
    assert sorted(p.name for p in out.iterdir()) == ["_headers", "index-meta.json", "index.json.gz"]


def test_index_schema_requires_version_2():
    index = build_index(catalog(make("a")), NOW)
    validator = _index_validator()
    for old in (1, 3, "2"):
        bad = dict(index, schema_version=old)
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(bad)


def test_v2_fields_copied_as_written():
    entry = make("a", genres=["Card", "Casino"], tags=["Multiplayer"], languages=["en", "es"],
                 pricing={"model": "one-time", "price": 5, "currency": "USD", "url": "https://example.com/buy"},
                 links=[{"url": "https://example.com/", "label": "Homepage"}], unsupported=True,
                 self_updating=True, contains=["A", "B"])
    entry["sources"][0].update(arch="x64", first_run_download_size=1024)
    index = build_index(catalog(entry), NOW)
    _index_validator().validate(index)
    assert index["entries"] == [dict(entry, extras=[])]
