import json
import subprocess

import responses

from catalog.config import MIRROR_BASE
from catalog.entries import write_entry
from catalog.mirror import WranglerUploader, put_main
from catalog.prune import main as prune_main
from catalog.prune import orphaned_keys, referenced_keys

SHA = "a" * 64
KEY = f"files/{SHA}/game.zip"


class FakeRunner:
    def __init__(self):
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        return subprocess.CompletedProcess(args, 0, "", "")


def mirror_entry(id_, key):
    return {"id": id_, "kind": "game", "title": id_.title(), "sources": [
        {"label": "Mirror", "url": MIRROR_BASE + key, "platform": "windows", "install": {"method": "zip"}}]}


@responses.activate
def test_wrangler_exists_asks_the_public_mirror():
    responses.add(responses.HEAD, MIRROR_BASE + KEY, status=200)
    responses.add(responses.HEAD, MIRROR_BASE + "files/b/x.zip", status=404)
    up = WranglerUploader("bucket", known_keys=[], runner=FakeRunner())
    assert up.exists(KEY) is True
    assert up.exists("files/b/x.zip") is False


@responses.activate
def test_wrangler_find_uses_known_keys_that_still_exist():
    responses.add(responses.HEAD, MIRROR_BASE + KEY, status=200)
    up = WranglerUploader("bucket", known_keys=[KEY, "files/" + "c" * 64 + "/y.7z"], runner=FakeRunner())
    assert up.find(SHA) == KEY
    assert up.find("d" * 64) is None


def test_wrangler_upload_and_delete_commands(tmp_path):
    f = tmp_path / "game.zip"
    f.write_bytes(b"x")
    run = FakeRunner()
    up = WranglerUploader("bucket", known_keys=[], runner=run)
    up.upload(f, KEY)
    up.delete(KEY)
    put, delete = run.calls
    assert put[put.index("r2"):] == ["r2", "object", "put", f"bucket/{KEY}", "--file", str(f),
                                     "--content-type", "application/zip", "--remote"]
    assert delete[delete.index("r2"):] == ["r2", "object", "delete", f"bucket/{KEY}", "--remote"]


@responses.activate
def test_put_main_uploads_and_prints_source(tmp_path, monkeypatch, capsys):
    f = tmp_path / "My Game.7z"
    f.write_bytes(b"hello")
    run = FakeRunner()
    monkeypatch.setattr("catalog.mirror.default_uploader", lambda entries_dir: WranglerUploader(
        "bucket", known_keys=[], runner=run))
    responses.add(responses.HEAD, MIRROR_BASE + "files/" + "0" * 64 + "/x", status=404)
    assert put_main([str(f), "--entries", str(tmp_path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out[0]["url"].startswith(MIRROR_BASE + "files/") and out[0]["url"].endswith("/My_Game.7z")
    assert out[0]["size"] == 5 and len(out[0]["sha256"]) == 64
    assert len(run.calls) == 1


def test_referenced_and_orphaned_keys():
    old = {"a": mirror_entry("a", KEY), "b": mirror_entry("b", "files/" + "b" * 64 + "/b.zip")}
    new = {"a": old["a"]}
    assert referenced_keys(old) == {KEY, "files/" + "b" * 64 + "/b.zip"}
    assert orphaned_keys(old, new) == ["files/" + "b" * 64 + "/b.zip"]


def test_orphan_still_used_by_another_entry_is_kept():
    old = {"a": mirror_entry("a", KEY), "b": mirror_entry("b", KEY)}
    assert orphaned_keys(old, {"b": old["b"]}) == []


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def test_prune_dry_run_lists_and_deletes_nothing(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    entries = repo / "entries"
    entries.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    write_entry(entries, mirror_entry("gone", KEY))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "x")
    (entries / "gone.json").unlink()
    run = FakeRunner()
    monkeypatch.setattr("catalog.prune.WranglerUploader", lambda bucket, known_keys: WranglerUploader(
        bucket, known_keys=known_keys, runner=run))
    assert prune_main(["--since", "HEAD", "--entries", str(entries)]) == 0
    assert KEY in capsys.readouterr().out
    assert run.calls == []
    assert prune_main(["--since", "HEAD", "--entries", str(entries), "--delete"]) == 0
    assert run.calls and run.calls[0][-2] == f"accessiblegames-files/{KEY}"
