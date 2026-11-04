import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"
FORMS = ROOT / ".github" / "ISSUE_TEMPLATE"
WORKFLOW_NAMES = ["validate", "publish", "mirror", "link-health"]
FORM_NAMES = ["submit-game", "suggest-update", "report-problem", "request-removal"]


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def triggers(doc):
    # PyYAML (YAML 1.1) parses the bare key "on" as boolean True.
    return doc.get("on", doc.get(True))


def test_workflows_parse():
    for name in WORKFLOW_NAMES:
        doc = load(WORKFLOWS / f"{name}.yml")
        assert doc["jobs"], name
        assert triggers(doc), name


def test_validate_runs_link_check():
    text = (WORKFLOWS / "validate.yml").read_text(encoding="utf-8")
    assert "catalog-links --changed-from" in text
    assert "--fail-on-dead" in text
    assert "fetch-depth: 0" in text


def test_mirror_uses_secrets_and_bucket_variable():
    text = (WORKFLOWS / "mirror.yml").read_text(encoding="utf-8")
    assert "vars.R2_BUCKET" in text
    assert "secrets.R2_BUCKET" not in text
    for name in ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"):
        assert f"secrets.{name}" in text
    assert "catalog-mirror" in text


def test_link_health_schedule():
    doc = load(WORKFLOWS / "link-health.yml")
    assert triggers(doc)["schedule"] == [{"cron": "0 6 * * 1"}]


def test_issue_forms_parse():
    for name in FORM_NAMES:
        form = load(FORMS / f"{name}.yml")
        assert form["name"] and form["body"], name
    config = load(FORMS / "config.yml")
    assert config["blank_issues_enabled"] is True
    submit = load(FORMS / "submit-game.yml")
    required = [
        item["attributes"]["label"]
        for item in submit["body"]
        if item.get("validations", {}).get("required")
    ]
    assert "Direct download URL" in required
    assert (FORMS / "request-removal.yml").exists()


def test_readme_has_removal_policy():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "requests are honored" in text


def test_no_agarchive_fetching_code():
    for base in (ROOT / "tools", ROOT / ".github"):
        for path in base.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                text = path.read_text(encoding="utf-8", errors="ignore")
                assert "agarchive.net/games" not in text, path


def test_mirror_runs_one_at_a_time_and_reuses_open_pr():
    doc = load(WORKFLOWS / "mirror.yml")
    assert doc["concurrency"] == {"group": "mirror", "cancel-in-progress": False}
    text = (WORKFLOWS / "mirror.yml").read_text(encoding="utf-8")
    assert "gh pr list --label mirror --state open" in text
    assert "--jq length" in text


def test_setup_order():
    text = (ROOT / "SETUP.md").read_text(encoding="utf-8")
    assert "--push" not in text

    def at(s):
        assert s in text, s
        return text.index(s)

    merge = at("git merge --ff-only feat/catalog-tools")
    create = at("gh repo create Accessible-Games/game-catalog")
    secrets = at("gh variable set R2_BUCKET --body accessiblegames-files")
    labels = at("gh label create mirror")
    pages = at("gh secret set CLOUDFLARE_API_TOKEN")
    perms = at("default_workflow_permissions=write")
    push = at("git push -u origin main")
    runs = at("gh workflow run publish.yml")
    assert merge < create < min(secrets, labels, pages, perms) <= max(secrets, labels, pages, perms) < push < runs
    assert "gh workflow run mirror.yml" in text[push:]


def test_publish_deploys_the_worker():
    doc = load(WORKFLOWS / "publish.yml")
    assert triggers(doc)["push"] == {"branches": ["main"]}
    text = (WORKFLOWS / "publish.yml").read_text(encoding="utf-8")
    assert "uv run catalog-index --out site" in text
    assert "cloudflare/wrangler-action@" in text
    assert "secrets.CLOUDFLARE_API_TOKEN" in text and "secrets.CLOUDFLARE_ACCOUNT_ID" in text
    assert "deploy-pages" not in text and "pages: write" not in text


def test_worker_serves_the_built_index_on_the_catalog_domain():
    raw = (ROOT / "wrangler.jsonc").read_text(encoding="utf-8")
    config = json.loads(re.sub(r"^\s*//.*$", "", raw, flags=re.M))
    assert config["name"] == "game-catalog"
    assert config["assets"]["directory"] == "./site"
    assert "main" not in config  # assets only, until the catalog needs API routes
    assert config["routes"] == [{"pattern": "catalog.accessiblegames.net", "custom_domain": True}]
    assert config["workers_dev"] is False


def test_github_token_limitation_documented():
    for name in ("SETUP.md", "README.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "GITHUB_TOKEN" in text, name
        assert "required check" in text, name


def test_setup_org_and_bucket_variable():
    text = (ROOT / "SETUP.md").read_text(encoding="utf-8")
    assert "gh secret set R2_BUCKET" not in text
    assert "accessible-games.github.io" not in text  # served by the Worker, not GitHub Pages
    assert "https://catalog.accessiblegames.net/index-meta.json" in text
    assert "Moving to an organization" not in text
    assert "after closing, run `gh workflow run mirror.yml`" in text
