"""MediaExtractor 契约:结果不可变、可序列化,注册表可插拔。"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _sample_result():
    from mase.multimodal.extractor import CandidateFact, ExtractionResult

    return ExtractionResult(
        full_text="Invoice #001 total 4200 EUR",
        candidate_facts=(
            CandidateFact(
                category="finance_budget", key="invoice_001_total", value="4200 EUR",
                confidence=0.9, evidence="total 4200 EUR",
            ),
        ),
        extractor_name="fake",
        model_name="none",
        extractor_version="1",
        warnings=(),
    )


def test_extraction_result_frozen_and_json_roundtrip():
    result = _sample_result()
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.full_text = "tampered"  # type: ignore[misc]

    payload = json.loads(result.to_json())
    assert payload["full_text"].startswith("Invoice")
    assert payload["candidate_facts"][0]["category"] == "finance_budget"
    assert payload["extractor_version"] == "1"


def test_registry_register_get_and_replace():
    from mase.multimodal.extractor import extractor_names, get_extractor_factory, register_extractor

    marker_a, marker_b = object(), object()
    register_extractor("t6-demo", lambda: marker_a)
    assert get_extractor_factory("t6-demo")() is marker_a
    register_extractor("t6-demo", lambda: marker_b)  # 同名替换,幂等重导入友好
    assert get_extractor_factory("t6-demo")() is marker_b
    assert "t6-demo" in extractor_names()
    assert get_extractor_factory("no-such") is None
