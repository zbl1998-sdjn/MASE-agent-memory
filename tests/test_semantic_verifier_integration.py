"""L2 语义验证器接线(opt-in):改写型记忆声明的核对进入答案审计管线。

L1(claim_verifier.verify_answer)的已声明边界是"逐字引用型"声明——答案把
`budget = 500元` 改写成"预算是五百块"时 L1 静默放过(UNTAGGED)。L2
(semantic_claim_verifier,确定性同义表+归一化,不调 LLM)补这个盲区:

- 默认关(`MASE_SEMANTIC_VERIFIER` 未设):审计行为与 L1-only 逐字节一致;
- opt-in 后只收紧不放宽:L1 UNTAGGED + L2 SUPPORTED → SEMANTIC_SUPPORTED
  (非 violation);L1 UNTAGGED + L2 CONTRADICTED → SEMANTIC_CONTRADICTED
  (violation,verdict 按 L1 规则合成);L2 UNKNOWN → 保持 UNTAGGED;
- L1 已打标的句子 L2 不得覆盖(逐字口径优先);
- 不确定语气护栏:"预算还没定下来"这类非断言句不得判 CONTRADICTED
  (可枚举不确定词表,白盒规则,防误杀)。
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _isolate(tmp_path, monkeypatch):
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "l2.db"))
    monkeypatch.delenv("MASE_SEMANTIC_VERIFIER", raising=False)


def _seed(predicate: str, value: str):
    from mase.governance.fact_contract import FactContract, new_fact_id
    from mase.governance.fact_store import propose_fact

    source = f"会议记录:{predicate} 定为 {value}。"
    return propose_fact(
        FactContract(
            fact_id=new_fact_id(),
            entity_id="user:alice",
            claim_type="project_fact",
            subject="alice",
            predicate=predicate,
            object_value=value,
            confidence=0.9,
            observed_at="2026-07-01T00:00:00Z",
        ),
        value,
        source_type="chat", source_id="m1", trust_level=3, source_full_text=source,
    )


def _audit(question: str, keywords: list[str], answer: str):
    from mase.governance.claim_verifier import verify_answer
    from mase.governance.evidence_pack import compile_evidence_pack

    pack = compile_evidence_pack(question, keywords)
    return verify_answer(answer, pack)


class TestDefaultOffUnchanged:
    def test_paraphrased_contradiction_stays_untagged_by_default(self, tmp_path, monkeypatch):
        """默认路径钉死:L1-only 下改写矛盾句是 UNTAGGED、verdict=pass。"""
        _isolate(tmp_path, monkeypatch)
        _seed("owner", "Alice")
        audit = _audit("谁负责这个项目?", ["owner"], "Bob owns the project.")
        assert audit.verdict == "pass"
        assert [s["tag"] for s in audit.spans] == ["UNTAGGED"]


class TestOptInSemanticLayer:
    def test_supported_face_is_fully_covered_by_l1(self, tmp_path, monkeypatch):
        """SUPPORTED 面无 L2 增量:L2 的支持条件(值逐字+谓词语境)是 L1
        (值逐字)的严格子集,凡 L2 能支持的句子 L1 必已打标——L2 开启时
        该面行为必须与 L1-only 一致,不引入新 tag。"""
        _isolate(tmp_path, monkeypatch)
        monkeypatch.setenv("MASE_SEMANTIC_VERIFIER", "1")
        fact = _seed("owner", "Alice")
        audit = _audit("谁负责这个项目?", ["owner"], "Alice owns the project.")
        span = audit.spans[0]
        assert span["tag"] == "SUPPORTED_BY_MEMORY"
        assert span["violation"] is False
        assert fact.fact_id in span["fact_ids"]
        assert audit.verdict == "pass"

    def test_paraphrased_contradiction_becomes_violation(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        monkeypatch.setenv("MASE_SEMANTIC_VERIFIER", "1")
        _seed("owner", "Alice")
        audit = _audit("谁负责这个项目?", ["owner"], "Bob owns the project.")
        span = audit.spans[0]
        assert span["tag"] == "SEMANTIC_CONTRADICTED"
        assert span["violation"] is True
        # pack 有 verified 支撑 → 按 L1 合成规则 revise(refuse 留给零支撑)。
        assert audit.verdict == "revise"

    def test_unknown_mention_stays_untagged_without_violation(self, tmp_path, monkeypatch):
        """提及治理谓词但语气不确定:不得升 violation(防误杀)。"""
        _isolate(tmp_path, monkeypatch)
        monkeypatch.setenv("MASE_SEMANTIC_VERIFIER", "1")
        _seed("budget", "500元")
        audit = _audit("预算多少?", ["budget"], "预算还没定下来。")
        span = audit.spans[0]
        assert span["violation"] is False
        assert span["tag"] in ("UNTAGGED",)
        assert audit.verdict == "pass"

    def test_l1_verbatim_tag_is_not_overridden(self, tmp_path, monkeypatch):
        """逐字命中已由 L1 打标(SUPPORTED_BY_MEMORY):L2 不得覆盖。"""
        _isolate(tmp_path, monkeypatch)
        monkeypatch.setenv("MASE_SEMANTIC_VERIFIER", "1")
        _seed("budget", "500元")
        audit = _audit("预算多少?", ["budget"], "预算是 500元。")
        span = audit.spans[0]
        assert span["tag"] == "SUPPORTED_BY_MEMORY"

    def test_unrelated_sentence_stays_untagged(self, tmp_path, monkeypatch):
        """与治理谓词无关的句子:L2 不评一般内容。"""
        _isolate(tmp_path, monkeypatch)
        monkeypatch.setenv("MASE_SEMANTIC_VERIFIER", "1")
        _seed("owner", "Alice")
        audit = _audit("谁负责?", ["owner"], "今天天气不错。")
        assert audit.spans[0]["tag"] == "UNTAGGED"
        assert audit.verdict == "pass"


class TestUncertaintyGuardInPoC:
    """PoC 纯函数层的不确定语气护栏(接线前提:先把误杀面钉死)。"""

    def _pack(self, tmp_path, monkeypatch, predicate: str, value: str):
        _isolate(tmp_path, monkeypatch)
        from mase.governance.evidence_pack import compile_evidence_pack

        _seed(predicate, value)
        return compile_evidence_pack("q", [predicate])

    def test_uncertain_sentence_is_unknown_not_contradicted(self, tmp_path, monkeypatch):
        from mase.governance.semantic_claim_verifier import verify_semantic_claims

        pack = self._pack(tmp_path, monkeypatch, "budget", "500元")
        for answer in ("预算还没定下来。", "The budget is not yet decided.", "预算待定。"):
            result = verify_semantic_claims(answer, pack)
            statuses = [j["status"] for j in result["judgments"]]
            assert "contradicted" not in statuses, f"不确定句被误判矛盾: {answer!r} -> {result}"

    def test_assertive_wrong_value_is_still_contradicted(self, tmp_path, monkeypatch):
        from mase.governance.semantic_claim_verifier import verify_semantic_claims

        pack = self._pack(tmp_path, monkeypatch, "budget", "500元")
        result = verify_semantic_claims("预算是 800元。", pack)
        statuses = [j["status"] for j in result["judgments"]]
        assert "contradicted" in statuses
