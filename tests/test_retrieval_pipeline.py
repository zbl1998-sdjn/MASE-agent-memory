"""检索补充阶段管线(架构切片⑤):默认零 stage/llm-judge 两级管道/异常隔离。"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from mase.benchmark_notetaker import BenchmarkNotetaker

_NEEDLE = (
    "Kenji's weekend ritual involves gliding across frozen ponds "
    "with blades strapped to his boots."
)


def _make_bn(tmp_path, monkeypatch) -> BenchmarkNotetaker:
    monkeypatch.delenv("MASE_DB_PATH", raising=False)
    monkeypatch.setenv("MASE_MEMORY_DIR", str(tmp_path))
    for flag in ("MASE_EVENT_SEMANTIC_RECALL", "MASE_LLM_JUDGE_RECALL"):
        monkeypatch.delenv(flag, raising=False)
    bn = BenchmarkNotetaker()
    bn.write(user_query="Tell me about weekends.", assistant_response=_NEEDLE,
             summary="Kenji weekend", thread_id="t1")
    bn.write(user_query="Dinner?", assistant_response="Kenji made pasta with tomato sauce.",
             summary="Kenji dinner", thread_id="t1")
    return bn


def _fake_vectors(monkeypatch, sims: dict[str, float]):
    """discover_events 的 embed 假实现:按内容片段给相似度构造向量。"""
    from mase import event_semantic_recall

    def _fake_embed(texts, *, model=None):
        out = []
        for t in texts:
            sim = next((v for frag, v in sims.items() if frag in t), None)
            if sim is None:
                out.append([1.0, 0.0])  # 查询向量
            else:
                out.append([sim, (1 - sim * sim) ** 0.5])
        return out

    monkeypatch.setattr(event_semantic_recall, "embed_texts", _fake_embed)


class TestDefaultOff:
    def test_no_stage_enabled_no_supplement(self, tmp_path, monkeypatch):
        bn = _make_bn(tmp_path, monkeypatch)
        from mase import retrieval_pipeline

        def _boom(*a, **k):
            raise AssertionError("no stage may run by default")

        monkeypatch.setattr(retrieval_pipeline, "_event_semantic_stage", _boom)
        monkeypatch.setattr(retrieval_pipeline, "_llm_judge_stage", _boom)
        results = bn.search(["Kenji"], full_query="What sport does Kenji practice?", limit=1)
        assert all(r.get("retrieval_reason") != "llm_judge_recall" for r in results)


class TestLlmJudgeStage:
    def test_judge_yes_rows_are_appended_with_reason(self, tmp_path, monkeypatch):
        bn = _make_bn(tmp_path, monkeypatch)
        monkeypatch.setenv("MASE_LLM_JUDGE_RECALL", "1")
        _fake_vectors(monkeypatch, {"frozen ponds": 0.45, "tomato sauce": 0.35})

        from mase import retrieval_pipeline

        def _fake_judge(query, texts, *, db_path=None, **kw):
            return ["frozen ponds" in t for t in texts]  # 只放行真 needle

        monkeypatch.setattr(retrieval_pipeline, "judge_relevance_batch", _fake_judge, raising=False)
        import mase.relevance_judge as rj
        monkeypatch.setattr(rj, "judge_relevance_batch", _fake_judge)

        results = bn.search(["Kenji", "sport"], full_query="What winter sport does Kenji practice?", limit=1)
        judged = [r for r in results if r.get("retrieval_reason") == "llm_judge_recall"]
        assert len(judged) == 1
        assert "frozen ponds" in str(judged[0]["content"])
        assert judged[0]["confidence"] == "low"

    def test_judge_no_rows_appends_nothing(self, tmp_path, monkeypatch):
        bn = _make_bn(tmp_path, monkeypatch)
        monkeypatch.setenv("MASE_LLM_JUDGE_RECALL", "1")
        _fake_vectors(monkeypatch, {"frozen ponds": 0.45, "tomato sauce": 0.35})
        import mase.relevance_judge as rj
        monkeypatch.setattr(rj, "judge_relevance_batch", lambda q, texts, **kw: [False] * len(texts))

        results = bn.search(["Kenji", "sport"], full_query="What winter sport does Kenji practice?", limit=1)
        assert all(r.get("retrieval_reason") != "llm_judge_recall" for r in results)


class TestStageIsolation:
    def test_failing_stage_does_not_break_search_or_other_stages(self, tmp_path, monkeypatch):
        bn = _make_bn(tmp_path, monkeypatch)
        monkeypatch.setenv("MASE_EVENT_SEMANTIC_RECALL", "1")
        monkeypatch.setenv("MASE_LLM_JUDGE_RECALL", "1")
        from mase import retrieval_pipeline

        def _boom(query, ctx):
            raise RuntimeError("stage down")

        monkeypatch.setitem(
            retrieval_pipeline.SUPPLEMENT_STAGES, "event_semantic",
            ("MASE_EVENT_SEMANTIC_RECALL", _boom),
        )
        _fake_vectors(monkeypatch, {"frozen ponds": 0.45, "tomato sauce": 0.35})
        import mase.relevance_judge as rj
        monkeypatch.setattr(rj, "judge_relevance_batch", lambda q, texts, **kw: [True] * len(texts))

        results = bn.search(["Kenji", "sport"], full_query="What winter sport does Kenji practice?", limit=1)
        assert results  # 主检索不受损
        assert any(r.get("retrieval_reason") == "llm_judge_recall" for r in results)  # 后续 stage 照跑

    def test_stages_do_not_duplicate_same_row(self, tmp_path, monkeypatch):
        bn = _make_bn(tmp_path, monkeypatch)
        monkeypatch.setenv("MASE_EVENT_SEMANTIC_RECALL", "1")
        monkeypatch.setenv("MASE_LLM_JUDGE_RECALL", "1")
        _fake_vectors(monkeypatch, {"frozen ponds": 0.60, "tomato sauce": 0.35})
        import mase.relevance_judge as rj
        monkeypatch.setattr(rj, "judge_relevance_batch", lambda q, texts, **kw: [True] * len(texts))

        results = bn.search(["Kenji", "sport"], full_query="What winter sport does Kenji practice?", limit=1)
        needle_hits = [r for r in results if "frozen ponds" in str(r.get("content"))]
        # 事件语义 stage(0.60 ≥ 0.55)先追加,judge stage 因 existing_ids 去重不再追加同一行
        assert len(needle_hits) == 1
        assert needle_hits[0]["retrieval_reason"] == "event_semantic_discovery"
