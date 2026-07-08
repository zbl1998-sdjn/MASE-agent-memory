"""engine 注入开关特征测试(P3 T3):MASE_EVIDENCE_PACK_INJECTION 开=证据包,关=原行为。"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import mase.engine as engine


class FakeRuntimeModel:
    def get_call_log(self) -> list[dict[str, Any]]:
        return []

    def describe_agent(self, agent: str, *, mode: str | None = None) -> dict[str, Any]:
        return {"agent": agent, "mode": mode}


class FakeRuntimeNotetaker:
    def search(self, keywords: list[str], **kwargs: Any) -> list[dict[str, Any]]:
        return [{"id": 1, "summary": "budget is 800"}]

    def write(self, **kwargs: Any) -> None:
        pass

    def fetch_all_chronological(self) -> list[dict[str, Any]]:
        return []


class FakePlan:
    def __init__(self) -> None:
        self.search_limit = 5
        self.use_multipass = False
        self.classification = type("Classification", (), {"problem_type": "current_state"})()

    def to_search_kwargs(self) -> dict[str, Any]:
        return {}

    def to_dict(self) -> dict[str, Any]:
        return {"search_limit": self.search_limit}


def _system(executor_log: list[dict[str, Any]]) -> Any:
    system = engine.MASESystem.__new__(engine.MASESystem)
    system.model_interface = FakeRuntimeModel()
    system.notetaker_agent = FakeRuntimeNotetaker()
    system._gc_threads = []
    system.call_router = lambda user_question: {"action": "search_memory", "keywords": ["800"]}  # type: ignore[method-assign]

    def _executor(**kwargs: Any) -> str:
        executor_log.append(kwargs)
        return "answer"

    system.call_executor = _executor  # type: ignore[method-assign]
    system._build_fact_sheet_with_notetaker = lambda **kwargs: ("legacy_fact_sheet", "facts")  # type: ignore[method-assign]
    system._select_collaboration_mode = lambda question, facts, mode: "off"  # type: ignore[method-assign]
    system._build_instruction_package = lambda question, facts, planner: ""  # type: ignore[method-assign]
    system.describe_executor_target = lambda **kwargs: {"mode": kwargs["mode"], "use_memory": kwargs["use_memory"]}  # type: ignore[method-assign]
    return system


def _patch_engine(monkeypatch) -> None:
    monkeypatch.setattr(engine, "select_executor_mode", lambda question, facts: "grounded")
    monkeypatch.setattr(engine, "use_deterministic_fact_sheet", lambda: True)
    monkeypatch.setattr(engine, "build_trace_steps", lambda **kwargs: [])
    monkeypatch.setattr(engine, "record_trace_payload", lambda **kwargs: "trace.jsonl")
    monkeypatch.setattr(engine, "is_long_memory", lambda: False)
    monkeypatch.setattr(engine, "is_long_context_qa", lambda: False)
    monkeypatch.setattr(engine, "is_multidoc_long_context", lambda: False)
    monkeypatch.setattr(engine, "determine_memory_heat", lambda question: "warm")
    monkeypatch.setattr(engine, "build_retrieval_plan", lambda *args, **kwargs: FakePlan())
    monkeypatch.setattr(engine, "multipass_allowed_for_task", lambda: False)
    monkeypatch.setenv("MASE_AUDIT_MARKDOWN", "0")
    monkeypatch.setenv("MASE_GC_AUTO", "0")


def _seed_fact(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "inject.db"))
    from mase.governance.fact_contract import FactContract, new_fact_id
    from mase.governance.fact_store import propose_fact

    propose_fact(
        FactContract(
            fact_id=new_fact_id(),
            entity_id="user:default",
            claim_type="project_fact",
            subject="project_facts",
            predicate="budget",
            object_value="800 元",
            confidence=0.9,
            observed_at="2026-07-04T00:00:00Z",
        ),
        "预算 800 元",
        source_type="memory_log",
        source_id="1",
        trust_level=5,
        source_full_text="会议纪要:预算 800 元。",
    )


def test_default_off_keeps_legacy_fact_sheet(tmp_path, monkeypatch):
    _patch_engine(monkeypatch)
    _seed_fact(tmp_path, monkeypatch)
    monkeypatch.delenv("MASE_EVIDENCE_PACK_INJECTION", raising=False)
    log: list[dict[str, Any]] = []
    engine.MASESystem.run_with_trace(_system(log), "预算 800?", log=False)
    assert log[0]["fact_sheet"] == "legacy_fact_sheet"  # 默认行为逐字节不变


def test_opt_in_replaces_fact_sheet_with_pack(tmp_path, monkeypatch):
    _patch_engine(monkeypatch)
    _seed_fact(tmp_path, monkeypatch)
    monkeypatch.setenv("MASE_EVIDENCE_PACK_INJECTION", "1")
    log: list[dict[str, Any]] = []
    engine.MASESystem.run_with_trace(_system(log), "预算 800?", log=False)
    sheet = log[0]["fact_sheet"]
    assert sheet.startswith("# Memory Evidence Pack")
    assert "800 元" in sheet and "## Answer Rules" in sheet


def test_enterprise_mode_defaults_to_evidence_pack(tmp_path, monkeypatch):
    _patch_engine(monkeypatch)
    _seed_fact(tmp_path, monkeypatch)
    monkeypatch.delenv("MASE_EVIDENCE_PACK_INJECTION", raising=False)
    monkeypatch.setenv("MASE_ENTERPRISE_MODE", "1")
    log: list[dict[str, Any]] = []
    engine.MASESystem.run_with_trace(_system(log), "预算 800?", log=False)
    assert log[0]["fact_sheet"].startswith("# Memory Evidence Pack")


def test_explicit_injection_off_overrides_enterprise_mode(tmp_path, monkeypatch):
    _patch_engine(monkeypatch)
    _seed_fact(tmp_path, monkeypatch)
    monkeypatch.setenv("MASE_ENTERPRISE_MODE", "1")
    monkeypatch.setenv("MASE_EVIDENCE_PACK_INJECTION", "0")
    log: list[dict[str, Any]] = []
    engine.MASESystem.run_with_trace(_system(log), "预算 800?", log=False)
    assert log[0]["fact_sheet"] == "legacy_fact_sheet"


def test_opt_in_falls_back_on_governance_error(tmp_path, monkeypatch):
    _patch_engine(monkeypatch)
    _seed_fact(tmp_path, monkeypatch)
    monkeypatch.setenv("MASE_EVIDENCE_PACK_INJECTION", "1")

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("governance down")

    monkeypatch.setattr("mase.governance.evidence_pack.compile_evidence_pack", _boom)
    log: list[dict[str, Any]] = []
    engine.MASESystem.run_with_trace(_system(log), "预算 800?", log=False)
    assert log[0]["fact_sheet"] == "legacy_fact_sheet"  # best-effort 回退


def test_hybrid_mode_prepends_pack_and_keeps_raw_sheet(tmp_path, monkeypatch):
    """hybrid:pack 前置 + 原文 fact sheet 保留(2026-07-08 行业消融实证:长对话
    逐字块优于纯抽取物;pack 给现行值/历史链,原文兜底召回缺口)。"""
    _patch_engine(monkeypatch)
    _seed_fact(tmp_path, monkeypatch)
    monkeypatch.setenv("MASE_EVIDENCE_PACK_INJECTION", "hybrid")
    log: list[dict[str, Any]] = []
    engine.MASESystem.run_with_trace(_system(log), "预算 800?", log=False)
    sheet = log[0]["fact_sheet"]
    assert sheet.startswith("# Memory Evidence Pack")
    assert "800 元" in sheet
    assert "legacy_fact_sheet" in sheet  # 原文兜底仍在
    assert sheet.index("# Memory Evidence Pack") < sheet.index("legacy_fact_sheet")


def test_hybrid_mode_with_empty_store_keeps_legacy_sheet_only(tmp_path, monkeypatch):
    """空治理库时 hybrid 不注入空 pack(422 例无库案例零回归保证)。"""
    _patch_engine(monkeypatch)
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "empty.db"))
    monkeypatch.setenv("MASE_EVIDENCE_PACK_INJECTION", "hybrid")
    log: list[dict[str, Any]] = []
    engine.MASESystem.run_with_trace(_system(log), "预算 800?", log=False)
    assert log[0]["fact_sheet"] == "legacy_fact_sheet"
