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


def test_mirror_uses_secrets():
    text = (WORKFLOWS / "mirror.yml").read_text(encoding="utf-8")
    assert "secrets.R2_BUCKET" in text
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
