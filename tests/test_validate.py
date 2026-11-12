import copy
import json
import pytest

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
    problems = validate_entries(catalog(make("g"), make("x", "extra", extends=["g", "nope"])))
    assert msgs(problems) == ["extends unknown entry 'nope'"]


def test_extends_must_name_games():
    entries = catalog(make("g"), make("rt", "runtime"), make("y", "extra", extends=["g"]),
                      make("x", "extra", extends=["g", "rt", "y"]))
    problems = validate_entries(entries)
    assert [p.entry_id for p in problems] == ["x", "x"]
    assert msgs(problems) == [
        "extends 'rt', which is not a game (its kind is 'runtime'); extends must name game entries",
        "extends 'y', which is not a game (its kind is 'extra'); extends must name game entries",
    ]


def test_extends_with_two_games():
    entries = catalog(make("g"), make("h"), make("x", "extra", extends=["g", "h"], required=True))
    assert validate_entries(entries) == []


def test_persist_accepted():
    for persist in ([], ["Saves/"], ["Saves", "*.sav", "data/profile?.ini", "maps/[ab]*.map", "Saves\\Slot1/"]):
        assert validate_entries(catalog(make("g", persist=persist))) == [], persist


def test_persist_only_on_games():
    entries = catalog(make("g"), make("x", "extra", extends=["g"], persist=["Saves/"]),
                      make("rt", "runtime", persist=[]))
    problems = validate_entries(entries)
    assert sorted(p.entry_id for p in problems) == ["rt", "x"]
    assert all(p.message.startswith("persist is only allowed on game entries") for p in problems)


@pytest.mark.parametrize("pattern, words", [
    ("/Saves/", "not an absolute path"),
    ("\\Saves", "not an absolute path"),
    ("C:/Games/Saves", "not an absolute path"),
    ("c:Saves", "not an absolute path"),
    ("../Saves", "must not use .."),
    ("Saves/../../x", "must not use .."),
    ("Saves\\..\\x", "must not use .."),
])
def test_persist_must_stay_in_the_game_folder(pattern, words):
    problems = msgs(validate_entries(catalog(make("g", persist=[pattern]))))
    assert len(problems) == 1 and words in problems[0] and problems[0].startswith("persist[0]:")


@pytest.mark.parametrize("pattern, words", [
    ("./Saves/", "starts with ./"),
    (".\\Saves", "starts with ./"),
    (" Saves/", "starts or ends with a space"),
    ("Saves/ ", "starts or ends with a space"),
    ("*.sav\t", "starts or ends with a space"),
])
def test_persist_rejects_patterns_the_app_never_matches(pattern, words):
    problems = msgs(validate_entries(catalog(make("g", persist=[pattern]))))
    assert len(problems) == 1 and words in problems[0] and "never match" in problems[0]


def test_persist_allows_a_lone_star():
    assert validate_entries(catalog(make("g", persist=["*"]))) == []


def test_persist_rejects_the_same_path_twice():
    for pair in (["Saves/", "Saves/"], ["Saves/", "saves/"], ["Saves\\", "Saves/"]):
        problems = msgs(validate_entries(catalog(make("g", persist=pair))))
        assert len(problems) == 1 and problems[0].startswith("persist[1]:") and "same as persist[0]" in problems[0]


@pytest.mark.parametrize("persist", ["Saves/", [""], [3], {"a": 1}])
def test_persist_shape(persist):
    problems = msgs(validate_entries(catalog(make("g", persist=persist))))
    assert problems and all(p.startswith("schema: persist") for p in problems)


def test_shared_extra_cannot_use_system_steps():
    reg = {"action": "registry", "hive": "HKCU", "key": "Software\\X", "name": "", "type": "REG_SZ", "value": "1"}
    com = {"action": "register", "path": "x.ocx"}
    shared = with_source(make("x", "extra", extends=["g", "h"]), steps=[reg, com])
    problems = validate_entries(catalog(make("g"), make("h"), shared))
    assert msgs(problems) == [
        "an extra that belongs to more than one game can't use register or registry steps: "
        "uninstalling it from one game would undo them for the others"]
    single = with_source(make("y", "extra", extends=["g"]), steps=[reg, com])
    assert validate_entries(catalog(make("g"), single)) == []
    copy_step = {"action": "copy", "from": "a", "to": "b"}
    harmless = with_source(make("z", "extra", extends=["g", "h"]), steps=[copy_step])
    assert validate_entries(catalog(make("g"), make("h"), harmless)) == []


STEP_ORDER_RULE = ("file steps (copy, move, delete) must come before system steps (registry, register, run), "
                   "because the app runs every file step first")
FILE_STEP_EXAMPLES = {
    "copy": {"action": "copy", "from": "a", "to": "b"},
    "move": {"action": "move", "from": "a", "to": "b"},
    "delete": {"action": "delete", "path": "a"},
}
SYSTEM_STEP_EXAMPLES = {
    "registry": {"action": "registry", "hive": "HKCU", "key": "Software\\X", "name": "", "type": "REG_SZ",
                 "value": "1"},
    "register": {"action": "register", "path": "x.ocx"},
    "run": {"action": "run", "path": "setup.exe"},
}


@pytest.mark.parametrize("system", sorted(SYSTEM_STEP_EXAMPLES))
@pytest.mark.parametrize("file", sorted(FILE_STEP_EXAMPLES))
def test_file_step_after_system_step_is_refused(file, system):
    steps = [SYSTEM_STEP_EXAMPLES[system], FILE_STEP_EXAMPLES[file]]
    problems = validate_entries(catalog(with_source(make("g"), steps=steps)))
    assert problems == [Problem("g", f"sources[0]: steps[1] ({file}) comes after steps[0] ({system}): "
                                     + STEP_ORDER_RULE)]


@pytest.mark.parametrize("steps", [
    [],
    ["copy", "move", "delete"],
    ["registry", "register", "run"],
    ["run", "register", "registry"],
    ["delete", "copy", "move", "register", "registry", "run"],
    ["copy", "run"],
])
def test_file_steps_before_system_steps_pass(steps):
    examples = {**FILE_STEP_EXAMPLES, **SYSTEM_STEP_EXAMPLES}
    entry = with_source(make("g"), steps=[examples[name] for name in steps])
    assert validate_entries(catalog(entry)) == []


def test_step_order_names_each_late_file_step_and_the_first_system_step():
    steps = [FILE_STEP_EXAMPLES["copy"], SYSTEM_STEP_EXAMPLES["register"], FILE_STEP_EXAMPLES["delete"],
             SYSTEM_STEP_EXAMPLES["run"], FILE_STEP_EXAMPLES["move"]]
    problems = validate_entries(catalog(with_source(make("g"), steps=steps)))
    assert msgs(problems) == [
        "sources[0]: steps[2] (delete) comes after steps[1] (register): " + STEP_ORDER_RULE,
        "sources[0]: steps[4] (move) comes after steps[1] (register): " + STEP_ORDER_RULE]


def test_step_order_is_checked_in_every_source():
    entry = make("g")
    good = [FILE_STEP_EXAMPLES["copy"], SYSTEM_STEP_EXAMPLES["register"]]
    bad = [SYSTEM_STEP_EXAMPLES["register"], FILE_STEP_EXAMPLES["copy"]]
    entry["sources"][0]["steps"] = good
    entry["sources"].append({**copy.deepcopy(entry["sources"][0]), "label": "Other",
                             "url": "https://example.com/y.zip", "steps": bad})
    assert msgs(validate_entries(catalog(entry))) == [
        "sources[1]: steps[1] (copy) comes after steps[0] (register): " + STEP_ORDER_RULE]


def test_step_order_applies_to_extras_and_runtimes():
    bad = [SYSTEM_STEP_EXAMPLES["register"], FILE_STEP_EXAMPLES["move"]]
    extra = with_source(make("x", "extra", extends=["g"]), steps=bad)
    runtime = with_source(make("r", "runtime"), steps=bad)
    problems = validate_entries(catalog(make("g"), extra, runtime))
    message = "sources[0]: steps[1] (move) comes after steps[0] (register): " + STEP_ORDER_RULE
    assert problems == [Problem("x", message), Problem("r", message)]


def test_step_order_leaves_malformed_steps_to_the_schema():
    steps = [SYSTEM_STEP_EXAMPLES["run"], "copy", {"action": "shred", "path": "a"}, {"from": "a", "to": "b"}]
    problems = msgs(validate_entries(catalog(with_source(make("g"), steps=steps))))
    assert problems and all(p.startswith("schema: sources/0/steps/") for p in problems)
    problems = msgs(validate_entries(catalog(with_source(make("g"), steps="copy"))))
    assert problems and all(p.startswith("schema: sources/0/steps") for p in problems)


def test_extends_must_not_repeat():
    problems = validate_entries(catalog(make("g"), make("x", "extra", extends=["g", "g"])))
    assert len(problems) == 1
    assert problems[0].entry_id == "x" and "schema: extends:" in problems[0].message
    assert "non-unique" in problems[0].message


def test_extends_repeated_unknown_reported_once():
    problems = msgs(validate_entries(catalog(make("x", "extra", extends=["nope", "nope"]))))
    assert problems.count("extends unknown entry 'nope'") == 1


def test_extends_must_not_be_empty():
    problems = validate_entries(catalog(make("g"), make("x", "extra", extends=[])))
    assert len(problems) == 1
    assert problems[0].entry_id == "x" and "schema: extends:" in problems[0].message


def test_extends_must_be_a_list():
    for old in ("g", None):
        problems = msgs(validate_entries(catalog(make("g"), make("x", "extra", extends=old))))
        assert len(problems) == 1 and problems[0].startswith("schema: extends:")


def test_extra_requires_extends():
    problems = validate_entries(catalog(make("x", "extra")))
    assert msgs(problems) == ["extra entries must set extends"]


def test_extends_only_on_extra_or_access_mod():
    entries = catalog(make("g"), make("h", extends=["g"]))
    assert any("extends" in p.message for p in validate_entries(entries))
    ok = catalog(make("g"), make("m", "access-mod", extends=["g"]), make("x", "extra", extends=["g"]))
    assert validate_entries(ok) == []


def test_required_only_on_extras():
    assert any("required" in p.message for p in validate_entries(catalog(make("g", required=True))))
    ok = catalog(make("g"), make("x", "extra", extends=["g"], required=True))
    assert validate_entries(ok) == []


def test_flags_and_approval_are_gone():
    entries = catalog(
        make("g"),
        make("x", "extra", extends=["g"], flags=["registration"], approval={"note": "ok by dev"}),
    )
    problems = msgs(validate_entries(entries))
    assert any("flags" in m for m in problems) and any("approval" in m for m in problems)
    assert not any("approval note" in m for m in problems)


def test_install_into_is_gone():
    problems = msgs(validate_entries(catalog(make("g"), make("x", "extra", extends=["g"], install_into="g"))))
    assert len(problems) == 1 and "install_into" in problems[0]


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


@pytest.mark.parametrize("url", [
    "https://agarchive.net\\@evil.example/x.7z",
    "https://evil.example\\@agarchive.net/x.7z",
    "https://exa mple.com/x.zip",
    "https://exa	mple.com/x.zip",
    "https://exa<mple.com/x.zip",
])
def test_bad_netloc_rejected(url):
    problems = validate_entries(catalog(with_source(make("a"), url=url)))
    assert problems, url
    link = validate_entries(catalog(make("a", links=[{"url": url}])))
    assert link, url


def test_agarchive_credit_link_allowed():
    e = make("a", links=[{"url": "https://agarchive.net/games/x.html", "label": "AGArchive"}])
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
    for value in ("mailto:dev@example.com", "/relative/page", "ftp://example.com/", "https:///x"):
        links = [{"url": "https://example.com/", "label": "Homepage"}, {"url": value}]
        problems = validate_entries(catalog(make("a", links=links)))
        assert any("links[1]" in p.message and "http or https" in p.message for p in problems), value
    ok = make("a", links=[{"url": "http://example.com/a page"}, {"url": "https://forum.example.com/t/1",
                                                                "label": "Forum topic"}])
    assert validate_entries(catalog(ok)) == []


def test_links_must_not_repeat_a_url():
    links = [{"url": "https://example.com/", "label": "Homepage"},
             {"url": "https://example.com/forum", "label": "Forum"},
             {"url": "https://example.com/", "label": "Site"}]
    problems = msgs(validate_entries(catalog(make("a", links=links))))
    assert problems == ["links[2]: URL is listed more than once (https://example.com/)"]


@pytest.mark.parametrize("links", [
    {"homepage": "https://example.com/"},
    [{"label": "Homepage"}],
    [{"url": "https://example.com/", "label": "Homepage", "kind": "home"}],
    ["https://example.com/"],
])
def test_links_must_be_a_list_of_url_and_label(links):
    problems = validate_entries(catalog(make("a", links=links)))
    assert problems and all(p.message.startswith("schema: ") for p in problems)


@pytest.mark.parametrize("pricing", [
    {"model": "free"},
    {"model": "free", "donate_url": "https://example.com/donate", "checked": "2026-11-09"},
    {"model": "free-with-purchases", "url": "https://example.com/store"},
    {"model": "free-to-try"},
    {"model": "free-to-try", "price": 15, "currency": "USD", "no_longer_sold": True},
    {"model": "pay-what-you-want", "price": 0, "suggested": 5, "currency": "EUR"},
    {"model": "pay-what-you-want"},
    {"model": "one-time", "price": 9.99, "currency": "GBP", "url": "https://example.com/buy",
     "note": "Full version adds 12 levels"},
    {"model": "one-time", "no_longer_sold": True},
    {"model": "subscription", "period": "month"},
    {"model": "subscription", "price": 30, "currency": "USD", "period": "year", "no_longer_sold": True},
    {"model": "free", "checked": "2028-02-29"},
])
def test_pricing_combinations_allowed(pricing):
    assert validate_entries(catalog(make("a", pricing=pricing))) == []


@pytest.mark.parametrize("pricing, message", [
    ({"model": "one-time", "price": 5}, "pricing: price needs a currency"),
    ({"model": "free-to-try", "price": 0}, "pricing: price needs a currency"),
    ({"model": "one-time", "currency": "USD"}, "pricing: currency is only used with a price"),
    ({"model": "pay-what-you-want", "suggested": 5, "currency": "USD"},
     "pricing: currency is only used with a price"),
    ({"model": "free", "price": 0, "currency": "USD"}, "pricing: price is not used with the free model"),
    ({"model": "free-with-purchases", "price": 2, "currency": "USD"},
     "pricing: price is not used with the free-with-purchases model"),
    ({"model": "one-time", "price": 5, "suggested": 8, "currency": "USD"},
     "pricing: suggested is only used with the pay-what-you-want model"),
    ({"model": "free", "suggested": 1}, "pricing: suggested is only used with the pay-what-you-want model"),
    ({"model": "subscription", "price": 5, "currency": "USD"},
     "pricing: period is required with the subscription model"),
    ({"model": "subscription"}, "pricing: period is required with the subscription model"),
    ({"model": "one-time", "period": "month"}, "pricing: period is only used with the subscription model"),
    ({"model": "free", "period": "year"}, "pricing: period is only used with the subscription model"),
    ({"model": "free", "no_longer_sold": True},
     "pricing: no_longer_sold is only used with the free-to-try, one-time or subscription model"),
    ({"model": "pay-what-you-want", "no_longer_sold": True},
     "pricing: no_longer_sold is only used with the free-to-try, one-time or subscription model"),
    ({"model": "free-with-purchases", "no_longer_sold": True},
     "pricing: no_longer_sold is only used with the free-to-try, one-time or subscription model"),
    ({"model": "free", "checked": "2026-02-30"}, "pricing.checked: not a real date (2026-02-30)"),
    ({"model": "free", "checked": "2026-13-01"}, "pricing.checked: not a real date (2026-13-01)"),
    ({"model": "one-time", "url": "mailto:sales@example.com"},
     "pricing.url: URL must be http or https with a host (mailto:sales@example.com)"),
    ({"model": "free", "donate_url": "/donate"},
     "pricing.donate_url: URL must be http or https with a host (/donate)"),
    ({"model": "free", "donate_url": "https:///donate"},
     "pricing.donate_url: URL must be http or https with a host (https:///donate)"),
])
def test_pricing_rules(pricing, message):
    assert msgs(validate_entries(catalog(make("a", pricing=pricing)))) == [message]


def test_pricing_problems_are_all_reported():
    pricing = {"model": "free", "price": 5, "suggested": 1, "period": "month"}
    assert msgs(validate_entries(catalog(make("a", pricing=pricing)))) == [
        "pricing: price needs a currency",
        "pricing: price is not used with the free model",
        "pricing: suggested is only used with the pay-what-you-want model",
        "pricing: period is only used with the subscription model",
    ]


def test_pricing_schema_errors_skip_rules_that_need_a_model():
    for pricing in ({"price": 5, "currency": "USD"}, {"suggested": 5, "period": "month", "no_longer_sold": True}):
        problems = msgs(validate_entries(catalog(make("a", pricing=pricing))))
        assert problems and all(m.startswith("schema: ") for m in problems), problems


@pytest.mark.parametrize("path", ["index.html", "Start.HTM", "game.exe", "run.bat", "play.cmd", "bin/Game.EXE",
                                  "game.hta", "Game.HTA", "sub/The snowball war.hta"])
def test_windows_launch_path_with_allowed_suffix_is_valid(path):
    e = make("a", launch={"windows": {"path": path}})
    assert validate_entries(catalog(e)) == []


@pytest.mark.parametrize("path", ["game.hta.txt", "readme.txt", "game"])
def test_windows_launch_path_with_other_suffix_is_a_problem(path):
    e = make("a", launch={"windows": {"path": path}})
    problems = msgs(validate_entries(catalog(e)))
    assert len(problems) == 1
    assert f"launch.windows.path {path!r}" in problems[0]
    assert ".html" in problems[0]


def test_launch_paths_on_other_platforms_are_not_checked():
    e = make("a", launch={"macos": {"path": "Game.app"}, "linux": {"path": "game"}})
    assert validate_entries(catalog(e)) == []
