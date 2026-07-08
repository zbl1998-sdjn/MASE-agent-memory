"""白盒语义候选发现:默认路径钉死 + opt-in 行为(假向量,全确定性)。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# 语义空间:reimburse_limit 与查询"expense ceiling"同向(cos≈0.994),
# lunch_spot 落弱线索带(cos≈0.518 ∈ [0.50, 0.55)),favorite_color 正交。
# 5K supersede 链:superseded 旧值(纯 25:50)与查询更相似(1.0),active 新值
# 稍低(0.97)——复刻 2026-07-08 POC 实况:旧链节点若可被发现会抢走 top_n 名额。
_FAKE_VECTORS = {
    "alice.reimburse_limit = 500 CNY": [1.0, 0.0, 0.0],
    "alice.favorite_color = blue": [0.0, 1.0, 0.0],
    "alice.travel_note = fly quietly": [0.0, 0.0, 1.0],
    "alice.lunch_spot = riverside cafe": [0.42, 0.9075, 0.0],
    "expense ceiling": [0.9, 0.1, 0.0],
    "alice.best_5k_time = 27:12": [0.98, 0.199, 0.0],
    "alice.best_5k_time = 25:50": [0.97, 0.243, 0.0],
    "best 5k run time": [1.0, 0.0, 0.0],
}


def _isolate_db(tmp_path, monkeypatch):
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "sem.db"))
    monkeypatch.delenv("MASE_SEMANTIC_DISCOVERY", raising=False)
    monkeypatch.delenv("MASE_EMBED_MODEL", raising=False)


def _fake_embedder(monkeypatch):
    from mase.governance import semantic_discovery

    calls: list[list[str]] = []

    def _fake(texts: list[str], *, model: str | None = None) -> list[list[float]]:
        calls.append(list(texts))
        missing = [t for t in texts if t not in _FAKE_VECTORS]
        assert not missing, f"fake embedder has no vector for {missing}"
        return [_FAKE_VECTORS[t] for t in texts]

    monkeypatch.setattr(semantic_discovery, "embed_texts", _fake)
    return calls


def _seed(predicate: str, value: str, *, claim_type: str = "project_fact"):
    from mase.governance.fact_contract import FactContract, new_fact_id
    from mase.governance.fact_store import propose_fact

    source = f"记录:{predicate} 为 {value}。"
    return propose_fact(
        FactContract(
            fact_id=new_fact_id(),
            entity_id="user:alice",
            claim_type=claim_type,
            subject="alice",
            predicate=predicate,
            object_value=value,
            confidence=0.9,
            observed_at="2026-07-01T00:00:00Z",
        ),
        value,
        source_type="chat", source_id="m1", trust_level=3, source_full_text=source,
    )


def test_default_off_keeps_plan_identical_and_never_embeds(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    from mase.governance import semantic_discovery
    from mase.governance.retrieval import retrieve_facts

    def _boom(*args, **kwargs):
        raise AssertionError("default path must never call the embedder")

    monkeypatch.setattr(semantic_discovery, "embed_texts", _boom)
    _seed("reimburse_limit", "500 CNY")
    plan, candidates = retrieve_facts(["expense ceiling"])
    assert plan.classifier == "none.v1"
    assert "semantic" not in plan.filters
    assert candidates == []  # 无关键词命中,默认路径不做任何语义补充


def test_discovery_finds_paraphrase_missed_by_keywords(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    monkeypatch.setenv("MASE_SEMANTIC_DISCOVERY", "1")
    _fake_embedder(monkeypatch)
    from mase.governance.retrieval import retrieve_facts

    target = _seed("reimburse_limit", "500 CNY")
    _seed("favorite_color", "blue")
    plan, candidates = retrieve_facts(["expense ceiling"])

    assert plan.classifier == "semantic_discovery.v1"
    assert plan.filters["semantic"]["model"]
    assert [c.fact.fact_id for c in candidates] == [target.fact_id]
    found = candidates[0]
    assert found.breakdown["semantic_similarity"] == pytest.approx(0.9938, abs=1e-3)
    assert found.breakdown["exact_entity_match"] == 0.0  # 机械分量不虚构
    assert found.breakdown["predicate_match"] == 0.0
    assert found.why_selected[0].startswith("语义发现")
    assert found.matched_keywords == ("expense ceiling",)


def test_keyword_hits_are_not_duplicated_by_discovery(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    monkeypatch.setenv("MASE_SEMANTIC_DISCOVERY", "1")
    _fake_embedder(monkeypatch)
    from mase.governance.retrieval import retrieve_facts

    target = _seed("reimburse_limit", "500 CNY")
    _, candidates = retrieve_facts(["reimburse_limit"])
    mine = [c for c in candidates if c.fact.fact_id == target.fact_id]
    assert len(mine) == 1
    assert "semantic_similarity" not in mine[0].breakdown  # 关键词命中走机械通道


def test_fact_vectors_are_cached_across_queries(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    monkeypatch.setenv("MASE_SEMANTIC_DISCOVERY", "1")
    calls = _fake_embedder(monkeypatch)
    from mase.governance.retrieval import retrieve_facts

    _seed("reimburse_limit", "500 CNY")
    _seed("favorite_color", "blue")
    retrieve_facts(["expense ceiling"])
    first_round = len(calls)
    retrieve_facts(["expense ceiling"])
    # 第二轮只重算查询向量(1 次调用),事实向量走 fact_embeddings 缓存。
    assert len(calls) == first_round + 1
    assert calls[-1] == ["expense ceiling"]


def test_discovered_quarantined_fact_stays_out_of_verified(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    monkeypatch.setenv("MASE_SEMANTIC_DISCOVERY", "1")
    _fake_embedder(monkeypatch)
    from mase.governance.evidence_pack import compile_evidence_pack

    quarantined = _seed("reimburse_limit", "500 CNY", claim_type="inference")
    assert quarantined.status == "quarantined"
    pack = compile_evidence_pack("报销上限是多少?", ["expense ceiling"])
    assert pack.verified == ()  # 语义发现不放宽 Verified 门槛
    assert any("500 CNY" in item for item in pack.do_not_assume)


def test_pack_unknowns_not_contradictory_after_discovery(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    monkeypatch.setenv("MASE_SEMANTIC_DISCOVERY", "1")
    _fake_embedder(monkeypatch)
    from mase.governance.evidence_pack import compile_evidence_pack

    _seed("reimburse_limit", "500 CNY")
    pack = compile_evidence_pack("报销上限是多少?", ["expense ceiling"])
    assert any("500 CNY" in str(v["claim"]) for v in pack.verified)
    assert pack.unknowns == ()  # 已语义覆盖的关键词不再报"未知"


def test_hint_band_lands_in_hints_section_not_candidates(tmp_path, monkeypatch):
    """[floor, threshold) 带:只进非应答线索节 + plan 审计;带下不现身任何地方。"""
    _isolate_db(tmp_path, monkeypatch)
    monkeypatch.setenv("MASE_SEMANTIC_DISCOVERY", "1")
    _fake_embedder(monkeypatch)
    from mase.governance.evidence_pack import compile_evidence_pack, render_markdown
    from mase.governance.retrieval import retrieve_facts

    target = _seed("reimburse_limit", "500 CNY")
    hint = _seed("lunch_spot", "riverside cafe")
    _seed("travel_note", "fly quietly")  # cos≈0,带下,任何地方都不该出现

    plan, candidates = retrieve_facts(["expense ceiling"])
    assert [c.fact.fact_id for c in candidates] == [target.fact_id]  # 线索不是候选
    hints_meta = plan.filters["semantic"]["hints"]
    assert [h["fact_id"] for h in hints_meta] == [hint.fact_id]
    assert 0.50 <= hints_meta[0]["similarity"] < 0.55

    pack = compile_evidence_pack("报销上限是多少?", ["expense ceiling"])
    assert [h["fact_id"] for h in pack.semantic_hints] == [hint.fact_id]
    assert "riverside cafe" in pack.semantic_hints[0]["claim"]
    assert all("riverside cafe" not in str(v["claim"]) for v in pack.verified)
    text = render_markdown(pack)
    assert "## Weak Semantic Hints(非应答)" in text
    assert "不作应答依据" in text
    assert "fly quietly" not in text


def test_quarantined_or_sensitive_facts_never_surface_as_hints(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    monkeypatch.setenv("MASE_SEMANTIC_DISCOVERY", "1")
    _fake_embedder(monkeypatch)
    from mase.governance.evidence_pack import compile_evidence_pack, render_markdown

    _seed("reimburse_limit", "500 CNY")
    quarantined = _seed("lunch_spot", "riverside cafe", claim_type="inference")
    assert quarantined.status == "quarantined"
    pack = compile_evidence_pack("报销上限是多少?", ["expense ceiling"])
    assert pack.semantic_hints == ()  # 隔离事实不得经线索节泄出
    assert "Weak Semantic Hints" not in render_markdown(pack)


def test_superseded_chain_nodes_never_returned_by_discovery(tmp_path, monkeypatch):
    """旧链节点(superseded)不得被语义发现召回——即便其相似度高于 active 链头。

    2026-07-08 POC 实况:top_n=1 名额被 superseded 旧值抢走,active 现行值
    落选 → pack Verified 空 → 弃答;且旧值可召回本身就是答旧值幻觉面。
    """
    _isolate_db(tmp_path, monkeypatch)
    _fake_embedder(monkeypatch)
    from mase.governance.semantic_discovery import discover

    old = _seed("best_5k_time", "27:12")
    new = _seed("best_5k_time", "25:50")
    assert old.status == "active" or new.status == "active"
    found = discover(["best 5k run time"], threshold=0.5, top_n=2)
    found_ids = {fid for fid, _s in found}
    assert new.fact_id in found_ids  # active 链头必须在
    assert old.fact_id not in found_ids  # superseded 节点绝不返回


def test_default_off_pack_has_no_hint_traces(tmp_path, monkeypatch):
    _isolate_db(tmp_path, monkeypatch)
    from mase.governance.evidence_pack import compile_evidence_pack, render_markdown

    _seed("reimburse_limit", "500 CNY")
    pack = compile_evidence_pack("报销上限是多少?", ["reimburse_limit"])
    assert pack.semantic_hints == ()
    assert pack.to_dict()["semantic_hints"] == []
    assert "Weak Semantic Hints" not in render_markdown(pack)
