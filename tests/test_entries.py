import json

import pytest

from catalog.entries import ENTRY_KEY_ORDER, EntryLoadError, load_entries, write_entry


def test_write_then_load_roundtrip(tmp_path):
    entry = {"id": "morokuma", "kind": "game", "title": "Café Ünïcode 日本語", "sources": []}
    path = write_entry(tmp_path, entry)
    assert path == tmp_path / "morokuma.json"
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert "日本語" in text
    assert load_entries(tmp_path) == {"morokuma": entry}


def test_write_entry_orders_keys(tmp_path):
    entry = {"zzz": 1, "title": "T", "checkver": {}, "id": "x", "aaa": 2, "kind": "game"}
    path = write_entry(tmp_path, entry)
    keys = list(json.loads(path.read_text(encoding="utf-8")))
    assert keys == ["id", "kind", "title", "checkver", "zzz", "aaa"]
    assert keys[:4] == [k for k in ENTRY_KEY_ORDER if k in keys]


def test_write_entry_refuses_overwrite(tmp_path):
    write_entry(tmp_path, {"id": "x", "title": "One"})
    with pytest.raises(FileExistsError):
        write_entry(tmp_path, {"id": "x", "title": "Two"})
    assert load_entries(tmp_path)["x"]["title"] == "One"


def test_write_entry_overwrite_true(tmp_path):
    write_entry(tmp_path, {"id": "x", "title": "One"})
    write_entry(tmp_path, {"id": "x", "title": "Two"}, overwrite=True)
    assert load_entries(tmp_path)["x"]["title"] == "Two"


def test_load_entries_bad_json(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(EntryLoadError) as exc:
        load_entries(tmp_path)
    assert exc.value.path == bad


def test_key_order_follows_schema_v2():
    assert ENTRY_KEY_ORDER == (
        "id", "kind", "title", "developer", "genres", "year", "description", "version",
        "self_updating", "pricing", "tags", "languages", "contains", "unsupported", "warning",
        "links", "sources", "launch", "dependencies", "extends", "install_into", "required",
        "detect", "checkver",
    )
    assert "flags" not in ENTRY_KEY_ORDER and "approval" not in ENTRY_KEY_ORDER


def test_write_entry_places_new_fields(tmp_path):
    entry = {"sources": [], "links": [], "pricing": {"model": "free"}, "tags": ["Idle"],
             "title": "T", "kind": "game", "id": "x", "self_updating": True, "warning": "W."}
    keys = list(json.loads(write_entry(tmp_path, entry).read_text(encoding="utf-8")))
    assert keys == ["id", "kind", "title", "self_updating", "pricing", "tags", "warning", "links", "sources"]
