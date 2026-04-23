from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_config_profile_registry_declares_intent_and_paths() -> None:
    payload = json.loads((ROOT / "config.profiles.json").read_text(encoding="utf-8"))
    profiles = payload["profiles"]

    assert profiles["published-local-default"]["path"] == "config.json"
    assert profiles["published-cloud-longmemeval"]["path"] == "config.lme_glm5.json"
    assert profiles["experimental-dual-gpu"]["path"] == "config.dual_gpu.json"
    assert profiles["published-nolima"]["path"] == "config.nolima.json"

    intents = {item["intent"] for item in profiles.values()}
    assert intents == {"baseline", "published", "experimental"}
