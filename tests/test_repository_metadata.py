"""Repository metadata tests for HACS and Home Assistant submission readiness."""

from __future__ import annotations

import json
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "custom_components" / "automagic" / "manifest.json"
HACS_CONFIG_PATH = REPO_ROOT / "hacs.json"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "validate.yml"
BRAND_DIR = REPO_ROOT / "custom_components" / "automagic" / "brand"
AGENTS_PATH = REPO_ROOT / "AGENTS.md"


def _read_json(path: Path) -> dict:
    """Load a repository JSON file."""
    return json.loads(path.read_text(encoding="utf-8"))


def _read_workflow(path: Path) -> dict:
    """Load the GitHub workflow without YAML 1.1 boolean coercion."""
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_manifest_declares_single_config_entry_service_integration():
    """Manifest should match the integration's actual setup model."""
    manifest = _read_json(MANIFEST_PATH)

    assert manifest["domain"] == "automagic"
    assert manifest["config_flow"] is True
    assert manifest["integration_type"] == "service"
    assert manifest["single_config_entry"] is True
    assert manifest["version"] == "0.2.5"


def test_manifest_keys_follow_home_assistant_ordering_rules():
    """Hassfest requires domain, name, then alphabetical ordering."""
    manifest = _read_json(MANIFEST_PATH)
    keys = list(manifest.keys())

    assert keys[:2] == ["domain", "name"]
    assert keys[2:] == sorted(keys[2:])


def test_hacs_config_targets_supported_home_assistant_version():
    """HACS metadata should advertise the supported minimum HA version."""
    hacs_config = _read_json(HACS_CONFIG_PATH)

    assert hacs_config["name"] == "AutoMagic - AI Automation Builder"
    assert hacs_config["render_readme"] is True
    assert hacs_config["homeassistant"] == "2024.10.0"


def test_repo_agents_file_documents_release_bumps():
    """Repo instructions should remind future agents to bump HACS versions."""
    content = AGENTS_PATH.read_text(encoding="utf-8")

    assert AGENTS_PATH.is_file()
    assert "commit and push" in content
    assert "manifest.json" in content
    assert "GitHub release/tag" in content


def test_local_brand_assets_exist_for_hacs_validation():
    """HACS default repo validation accepts a local brand directory."""
    assert (BRAND_DIR / "icon.png").is_file()
    assert (BRAND_DIR / "logo.png").is_file()


def test_validate_workflow_runs_hacs_without_skipping_brands():
    """The HACS validation workflow should enforce brand checks."""
    workflow = _read_workflow(WORKFLOW_PATH)

    assert "workflow_dispatch" in workflow["on"]
    assert workflow["jobs"]["hacs"]["steps"][0]["uses"] == "actions/checkout@v5"
    assert workflow["jobs"]["hassfest"]["steps"][0]["uses"] == "actions/checkout@v5"
    assert workflow["jobs"]["tests"]["steps"][0]["uses"] == "actions/checkout@v5"
    assert workflow["jobs"]["tests"]["steps"][1]["uses"] == "actions/setup-python@v6"

    hacs_step = next(
        step for step in workflow["jobs"]["hacs"]["steps"]
        if step.get("uses") == "hacs/action@main"
    )
    assert hacs_step["with"]["category"] == "integration"
    assert "ignore" not in hacs_step["with"]

    hassfest_step = next(
        step for step in workflow["jobs"]["hassfest"]["steps"]
        if step.get("uses") == "home-assistant/actions/hassfest@master"
    )
    assert hassfest_step["uses"] == "home-assistant/actions/hassfest@master"
