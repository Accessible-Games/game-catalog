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


@pytest.mark.parametrize("field", [
    {"flags": ["abandoned"]},
    {"approval": {"note": "ok by dev"}},
])
def test_rejects_removed_v1_fields(field):
    with pytest.raises(jsonschema.ValidationError):
        validate(make(**field))


GENRES = ["Action", "Adventure", "Arcade", "Board and dice", "Card", "Casino", "Educational", "Fighting",
          "Incremental", "Interactive fiction", "Music and rhythm", "Platformer", "Puzzle", "Racing", "Role-playing",
          "Shooter", "Simulation", "Sports", "Strategy", "Trivia", "Word"]


def test_every_genre_accepted():
    for genre in GENRES:
        validate(make(genres=[genre]))
    validate(make(genres=["Strategy", "Card", "Word"]))
    assert load_schema()["$defs"]["fields"]["properties"]["genres"]["items"]["enum"] == GENRES


@pytest.mark.parametrize("genres", [
    [], ["Strategy", "Card", "Word", "Puzzle"], ["Card", "Card"], ["card"], ["Board game"], "Card",
])
def test_rejects_bad_genres(genres):
    with pytest.raises(jsonschema.ValidationError):
        validate(make(genres=genres))


def test_tags():
    validate(make(tags=[]))
    validate(make(tags=["Multiplayer", "Roguelike", "Idle", "Survival", "Horror", "Side-scroller"]))
    for bad in (["Multiplayer", "Multiplayer"], ["multiplayer"], ["Co-op"], ["Sidescroller"]):
        with pytest.raises(jsonschema.ValidationError):
            validate(make(tags=bad))


def test_languages():
    validate(make(languages=["en", "fr", "ja", "pt"]))
    for bad in (["en", "en"], ["EN"], ["eng"], ["en-US"], ["e"], [1]):
        with pytest.raises(jsonschema.ValidationError):
            validate(make(languages=bad))


def test_contains_and_warning_are_text():
    validate(make(contains=["Game One", "Game Two"], warning="Some antivirus programs flag the installer."))
    for bad in ({"contains": "Game One"}, {"contains": [1]}, {"warning": ["x"]}):
        with pytest.raises(jsonschema.ValidationError):
            validate(make(**bad))


@pytest.mark.parametrize("field", ["unsupported", "self_updating"])
def test_true_only_booleans(field):
    validate(make(**{field: True}))
    for bad in (False, "true", 1):
        with pytest.raises(jsonschema.ValidationError):
            validate(make(**{field: bad}))


FULL_PRICING = {
    "model": "subscription", "price": 4.99, "currency": "USD", "period": "month", "checked": "2026-11-09",
    "no_longer_sold": True, "url": "https://example.com/buy", "donate_url": "https://example.com/donate",
    "note": "Full version adds 12 levels",
}


def test_pricing_fields():
    validate(make(pricing=FULL_PRICING))
    for model in ("free", "free-to-try", "pay-what-you-want", "one-time", "subscription", "free-with-purchases"):
        validate(make(pricing={"model": model}))
    validate(make(pricing={"model": "pay-what-you-want", "price": 0, "suggested": 5, "currency": "EUR"}))


@pytest.mark.parametrize("pricing", [
    {},
    {"price": 5, "currency": "USD"},
    {"model": "paid"},
    {"model": "one-time", "price": -1, "currency": "USD"},
    {"model": "one-time", "price": "5", "currency": "USD"},
    {"model": "pay-what-you-want", "price": 0, "suggested": -2, "currency": "USD"},
    {"model": "one-time", "price": 5, "currency": "usd"},
    {"model": "one-time", "price": 5, "currency": "US$"},
    {"model": "one-time", "price": 5, "currency": "USDX"},
    {"model": "subscription", "period": "week"},
    {"model": "free", "checked": "09/11/2026"},
    {"model": "free", "checked": "2026-11-9"},
    {"model": "one-time", "no_longer_sold": False},
    {"model": "free", "note": 3},
    {"model": "free", "url": 3},
    {"model": "free", "sale": True},
])
def test_rejects_bad_pricing(pricing):
    with pytest.raises(jsonschema.ValidationError):
        validate(make(pricing=pricing))


def test_links_are_url_and_label():
    validate(make(links=[]))
    validate(make(links=[{"url": "https://example.com/"}, {"url": "https://example.com/forum", "label": "Forum"}]))
    for bad in ({"homepage": "https://example.com/"}, [{"label": "Homepage"}], [{"url": "https://example.com/",
                                                                               "title": "x"}]):
        with pytest.raises(jsonschema.ValidationError):
            validate(make(links=bad))


def test_source_arch_and_first_run_download_size():
    for arch in ("x64", "x86", "arm64", "universal"):
        entry = make()
        entry["sources"][0].update(arch=arch, first_run_download_size=0)
        validate(entry)
    for bad in ({"arch": "amd64"}, {"arch": "ARM64"}, {"first_run_download_size": -1},
                {"first_run_download_size": 1.5}):
        entry = make()
        entry["sources"][0].update(bad)
        with pytest.raises(jsonschema.ValidationError):
            validate(entry)


def test_tar_install_method():
    entry = make()
    entry["sources"][0]["install"] = {"method": "tar", "extract_dir": "game"}
    validate(entry)


@pytest.mark.parametrize("detect", [
    {"file": "%WINDIR%\\SysWOW64\\msvbvm60.dll"},
    {"registry": {"hive": "HKCR", "key": "CLSID\\{X}\\InprocServer32"}},
    {"registry": {"hive": "HKLM", "key": "SOFTWARE\\Microsoft\\MSTTS", "name": "InstallDir"}},
    {"registry": {"hive": "HKCU", "key": "Software\\X", "name": ""}},
])
def test_detect_shapes(detect):
    validate(make(kind="runtime", detect=detect))


@pytest.mark.parametrize("detect", [
    {},
    {"path": "x.dll"},
    {"file": "x.dll", "registry": {"hive": "HKCR", "key": "k"}},
    {"file": "x.dll", "exists": True},
    {"registry": {"hive": "HKEY_LOCAL_MACHINE", "key": "k"}},
    {"registry": {"hive": "HKU", "key": "k"}},
    {"registry": {"hive": "HKLM"}},
    {"registry": {"hive": "HKLM", "key": "k", "value": "v"}},
    {"registry": "HKLM\\k"},
])
def test_rejects_other_detect_shapes(detect):
    with pytest.raises(jsonschema.ValidationError):
        validate(make(kind="runtime", detect=detect))


def test_accepts_access_mod_kind():
    validate(make(kind="access-mod"))


def test_step_registry_requires_hive():
    entry = make()
    entry["sources"][0]["steps"] = [
        {"action": "registry", "key": r"Software\X", "name": "n", "type": "REG_SZ", "value": "v"}
    ]
    with pytest.raises(jsonschema.ValidationError):
        validate(entry)
    entry["sources"][0]["steps"][0]["hive"] = "HKCU"
    validate(entry)


def test_extract_dir_allowed():
    entry = make()
    entry["sources"][0]["install"] = {"method": "7z", "extract_dir": "game"}
    validate(entry)
