import copy
import json

import jsonschema
import pytest

from catalog.entries import ROOT, load_schema

MINIMAL = {
    "id": "some-game",
    "kind": "game",
    "title": "Some Game",
    "sources": [
        {
            "label": "Developer site",
            "url": "https://example.com/game.zip",
            "platform": "windows",
            "install": {"method": "zip"},
        }
    ],
}


def validate(entry):
    jsonschema.Draft202012Validator(load_schema()).validate(entry)


def make(**changes):
    entry = copy.deepcopy(MINIMAL)
    entry.update(changes)
    return entry


def test_seed_entries_valid():
    files = sorted((ROOT / "entries").glob("*.json"))
    assert files
    for path in files:
        validate(json.loads(path.read_text(encoding="utf-8")))


def test_minimal_valid():
    validate(MINIMAL)


def test_rejects_unknown_key():
    with pytest.raises(jsonschema.ValidationError):
        validate(make(colour="red"))


def test_rejects_bad_id():
    with pytest.raises(jsonschema.ValidationError):
        validate(make(id="Bad Id"))


def test_rejects_unknown_flag():
    with pytest.raises(jsonschema.ValidationError):
        validate(make(flags=["cracked"]))


def test_accepts_access_mod_kind():
    validate(make(kind="access-mod"))


def test_step_registry_requires_hive():
    entry = make()
    entry["sources"][0]["steps"] = [
        {"action": "registry", "key": "Software\X", "name": "n", "type": "REG_SZ", "value": "v"}
    ]
    with pytest.raises(jsonschema.ValidationError):
        validate(entry)
    entry["sources"][0]["steps"][0]["hive"] = "HKCU"
    validate(entry)


def test_extract_dir_allowed():
    entry = make()
    entry["sources"][0]["install"] = {"method": "7z", "extract_dir": "game"}
    validate(entry)
