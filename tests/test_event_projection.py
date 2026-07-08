"""事件→事实投影切片① gold set(设计 2026-07-08 §5,全确定性)。"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _isolate_db(tmp_path, monkeypatch):
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "proj.db"))


def _write_event(content: str, *, role: str = "user", thread: str = "t1") -> str:
    from mase_tools.memory.api import mase2_write_interaction

    return mase2_write_interaction(thread, role, content)


def _project(**kw):
    from mase.governance.event_projection import project_events

    return project_events(**kw)


def _facts(status: str | None = None):
    from mase.governance.fact_store import list_facts

    return list_facts(status=status)


def test_kv_events_become_located_active_facts(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    from mase.governance.fact_store import get_fact

    _write_event("会议纪要:\n项目预算: 500 元\n负责人: 张三")
    _write_event("今天天气不错,我们聊聊周末的计划吧。")  # 闲聊,零产出
    report = _project()
    assert report["events_projected"] == 1
    assert report["events_no_facts"] >= 1
    assert report["facts_by_status"].get("active") == 2
    actives = _facts(status="active")
    assert {f["predicate"] for f in actives} == {"项目预算", "负责人"}
    detail = get_fact(actives[0]["fact_id"])
    assert detail is not None
    spans = detail["evidence"]
    assert any(s["source_type"] == "memory_log" and s["span_start"] is not None for s in spans)


def test_same_key_update_supersedes_and_projection_is_idempotent(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    _write_event("项目预算: 500 元")
    first = _project()
    assert first["facts_by_status"].get("active") == 1
    _write_event("项目预算: 800 元")  # 同键形更新(切片①按键形匹配,无模糊归并)
    second = _project()
    assert second["events_skipped_already_projected"] >= 1  # 旧事件不重投
    assert second["facts_by_status"].get("active") == 1
    actives = [f for f in _facts(status="active") if f["predicate"] == "项目预算"]
    superseded = [f for f in _facts(status="superseded") if f["predicate"] == "项目预算"]
    assert len(actives) == 1 and actives[0]["object"] == "800 元"
    assert len(superseded) == 1 and superseded[0]["object"] == "500 元"
    third = _project()
    assert third["events_projected"] == 0 and third["facts_proposed"] == 0  # 幂等


def test_assistant_events_are_not_projected(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    _write_event("汇总: 项目预算: 999 元", role="assistant")
    report = _project()
    assert report["events_projected"] == 0
    assert _facts() == []


def test_pii_event_is_quarantined_by_gate(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    _write_event("联系方式: 13800138000")
    report = _project()
    assert report["facts_by_status"].get("quarantined", 0) >= 1
    assert not [f for f in _facts(status="active") if "138" in str(f["object"])]


def test_facade_reports_counts(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    from mase_tools.memory.api import mase2_project_events

    _write_event("截止日期: 7月15日")
    report = mase2_project_events()
    assert report["facts_proposed"] == 1
    assert report["facts_by_status"].get("active") == 1


def _mk_fact(key, value, evidence):
    from mase.multimodal.extractor import CandidateFact

    return CandidateFact(category="general_facts", key=key, value=value, confidence=0.9, evidence=evidence)


def test_llm_extractor_requires_model_interface(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    import pytest

    with pytest.raises(ValueError, match="model_interface"):
        _project(extractor="llm")
    with pytest.raises(ValueError, match="unknown extractor"):
        _project(extractor="magic")


def test_llm_extractor_projects_dialogue_facts(tmp_path, monkeypatch):
    """切片③:LLM 抽取器走同一 facade 通道(候选留痕/supersede/门控复用)。"""
    _isolate_db(tmp_path, monkeypatch)

    def _fake_extract(mi, content):
        if "5K" in content:
            return [_mk_fact("running_5k_best_time", "27:12", "personal best time in a charity 5K run with a time of 27:12")]
        return []

    monkeypatch.setattr("mase.governance.dialogue_facts.extract_dialogue_facts", _fake_extract)
    _write_event("I set a personal best time in a charity 5K run with a time of 27:12.")
    _write_event("今天天气不错。")
    report = _project(extractor="llm", model_interface=object())
    assert report["events_projected"] == 1
    assert report["facts_by_status"].get("active") == 1
    actives = _facts(status="active")
    assert actives[0]["predicate"] == "running_5k_best_time"


def test_kv_default_never_touches_llm_extractor(tmp_path, monkeypatch):
    """默认路径零 LLM(切片①行为字节不变)。"""
    _isolate_db(tmp_path, monkeypatch)

    def _boom(*a, **k):
        raise AssertionError("kv path must not call the llm extractor")

    monkeypatch.setattr("mase.governance.dialogue_facts.extract_dialogue_facts", _boom)
    _write_event("项目预算: 500 元")
    report = _project()
    assert report["facts_by_status"].get("active") == 1


def test_key_merge_flag_chains_synonym_keys(tmp_path, monkeypatch):
    """MASE_KEY_MERGE=1:同义键归并到既有键,supersede 成链。"""
    _isolate_db(tmp_path, monkeypatch)
    from mase.governance import event_projection

    calls = iter([
        [_mk_fact("running_5k_best_time", "27:12", "a time of 27:12")],
        [_mk_fact("running_personal_best_time", "25:50", "best time of 25:50")],
    ])
    monkeypatch.setattr("mase.governance.dialogue_facts.extract_dialogue_facts", lambda mi, c: next(calls))
    monkeypatch.setattr(event_projection, "canonical_key", lambda new, existing: "running_5k_best_time" if existing else new)
    monkeypatch.setenv("MASE_KEY_MERGE", "1")
    _write_event("first 5K: a time of 27:12")
    _write_event("new best time of 25:50")
    _project(extractor="llm", model_interface=object())
    actives = [f for f in _facts(status="active") if f["predicate"] == "running_5k_best_time"]
    superseded = [f for f in _facts(status="superseded") if f["predicate"] == "running_5k_best_time"]
    assert len(actives) == 1 and actives[0]["object"] == "25:50"
    assert len(superseded) == 1 and superseded[0]["object"] == "27:12"
