from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_resolve_config_profile_name_matches_repo_root_config() -> None:
    from benchmarks.runner import _resolve_config_profile_name, BASE_DIR

    profiles = {"published-local-default": {"path": "config.json", "intent": "published"}}
    result = _resolve_config_profile_name(BASE_DIR / "config.json", profiles)
    assert result == "published-local-default"


def test_resolve_config_profile_name_rejects_external_path_with_same_filename(tmp_path) -> None:
    """A config.json outside BASE_DIR must NOT match any registered profile."""
    from benchmarks.runner import _resolve_config_profile_name

    profiles = {"published-local-default": {"path": "config.json", "intent": "published"}}
    external_path = tmp_path / "config.json"
    result = _resolve_config_profile_name(external_path, profiles)
    assert result is None


def test_config_profile_registry_declares_intent_and_paths() -> None:
    payload = json.loads((ROOT / "config.profiles.json").read_text(encoding="utf-8"))
    profiles = payload["profiles"]

    assert profiles["published-local-default"]["path"] == "config.json"
    assert profiles["published-cloud-longmemeval"]["path"] == "config.lme_glm5.json"
    assert profiles["experimental-dual-gpu"]["path"] == "config.dual_gpu.json"
    assert profiles["published-nolima"]["path"] == "config.nolima.json"

    intents = {item["intent"] for item in profiles.values()}
    assert intents == {"baseline", "published", "experimental"}
