"""语义键归并特征测试(假向量,全确定性)。"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pytest

# 语义空间:两个 5K 键同向,bikes 键正交。
# cos(5k, personal) = 0.96 精确(0.96/sqrt(0.96^2+0.28^2)=0.96),用于阈值门控测试。
_VECS = {
    "running 5k best time": [1.0, 0.0, 0.0],
    "running personal best time": [0.96, 0.28, 0.0],
    "bikes owned count": [0.0, 1.0, 0.0],
}


@pytest.fixture(autouse=True)
def _fake_embed(monkeypatch):
    from mase.governance import key_merge

    def _fake(texts, *, model=None):
        return [_VECS[t] for t in texts]

    monkeypatch.setattr(key_merge, "embed_texts", _fake)
    monkeypatch.delenv("MASE_KEY_MERGE_THRESHOLD", raising=False)


def test_synonym_key_merges_to_existing():
    from mase.governance.key_merge import canonical_key

    out = canonical_key("running_personal_best_time", ["running_5k_best_time", "bikes_owned_count"])
    assert out == "running_5k_best_time"


def test_unrelated_key_stays_itself():
    from mase.governance.key_merge import canonical_key

    out = canonical_key("bikes_owned_count", ["running_5k_best_time"])
    assert out == "bikes_owned_count"


def test_exact_match_short_circuits_without_embedding(monkeypatch):
    from mase.governance import key_merge

    def _boom(*a, **k):
        raise AssertionError("exact/empty path must not embed")

    monkeypatch.setattr(key_merge, "embed_texts", _boom)
    assert key_merge.canonical_key("k", ["k", "other"]) == "k"
    assert key_merge.canonical_key("k", []) == "k"


def test_threshold_gates_weak_matches(monkeypatch):
    from mase.governance.key_merge import canonical_key

    # 阈值抬到 0.98:0.96 的近义键不再归并。
    monkeypatch.setenv("MASE_KEY_MERGE_THRESHOLD", "0.98")
    out = canonical_key("running_personal_best_time", ["running_5k_best_time"])
    assert out == "running_personal_best_time"


def test_flag_default_off():
    from mase.governance.key_merge import key_merge_enabled

    assert key_merge_enabled() is False
