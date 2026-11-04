import gzip
import hashlib
import json

import jsonschema
import pytest
from referencing import Registry, Resource

from catalog.entries import ROOT
from catalog.index import SCHEMA_VERSION, build_index, main, write_index

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
    assert index["schema_version"] == SCHEMA_VERSION == 1
    assert index["generated_at"] == NOW
    assert [e["id"] for e in index["entries"]] == ["alpha", "mid", "zeta"]


def test_extras_derived():
    entries = catalog(
        make("g"),
        make("e2", kind="extra", extends="g"),
        make("e1", kind="extra", extends="g", required=True),
    )
    by_id = {e["id"]: e for e in build_index(entries, NOW)["entries"]}
    assert by_id["g"]["extras"] == [{"id": "e1", "required": True}, {"id": "e2", "required": False}]
    assert by_id["e1"]["extras"] == []
    assert "extras" not in entries["g"]


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
        "schema_version": 1,
        "generated_at": NOW,
        "entry_count": 1,
        "sha256": hashlib.sha256(gz.read_bytes()).hexdigest(),
        "index_url": "index.json.gz",
    }
    assert json.loads(gzip.decompress(gz.read_bytes())) == index


def test_cname_written(tmp_path):
    write_index(build_index(catalog(make("a")), NOW), tmp_path)
    assert (tmp_path / "CNAME").read_text() == "catalog.accessiblegames.net\n"


def _index_validator():
    entry_schema = json.loads((ROOT / "schema" / "entry.schema.json").read_text(encoding="utf-8"))
    index_schema = json.loads((ROOT / "schema" / "index.schema.json").read_text(encoding="utf-8"))
    registry = Registry().with_resources([
        ("entry.schema.json", Resource.from_contents(entry_schema)),
        (entry_schema["$id"], Resource.from_contents(entry_schema)),
    ])
    return jsonschema.Draft202012Validator(index_schema, registry=registry)


def test_index_validates_against_index_schema():
    entries = catalog(make("g"), make("e1", kind="extra", extends="g", required=True))
    index = build_index(entries, NOW)
    validator = _index_validator()
    validator.validate(index)
    bad = json.loads(json.dumps(index))
    bad["entries"][0]["colour"] = "red"
    with pytest.raises(jsonschema.ValidationError):
        validator.validate(bad)


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
    assert sorted(p.name for p in out.iterdir()) == ["CNAME", "index-meta.json", "index.json.gz"]
