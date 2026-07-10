"""事件路径语义候选发现:默认路径钉死 + opt-in 行为(假向量,全确定性)。

镜像 tests/test_semantic_discovery.py 的测试风格,但针对 memory_log 而非
facts 表——两条语义发现路径独立开关、独立缓存表,测试也分开。
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from mase.benchmark_notetaker import BenchmarkNotetaker

# Kenji 需要一个语义空间:滑冰描写与查询"winter sport"同向但零字面重合;
# 两个字面 decoy(冬天抱怨/运动纪录片)与查询正交,不该被语义发现选中。
_FAKE_VECTORS = {
    "User: Tell me about your weekends.\nAssistant: Kenji's weekend ritual involves gliding across frozen ponds with blades strapped to his boots, weaving between the other neighborhood kids until the light fades.\nSummary: Kenji weekend ritual": [
        0.95,
        0.10,
        0.0,
    ],
    "User: How do you feel about the cold?\nAssistant: Kenji says winter is his least favorite season because of the cold commute.\nSummary: Kenji winter complaint": [
        0.0,
        0.0,
        1.0,
    ],
    "User: What did you watch last night?\nAssistant: Kenji watched a sport documentary about mountain climbing.\nSummary: Kenji sport documentary": [
        0.0,
        1.0,
        0.0,
    ],
    "What winter sport does Kenji practice?": [1.0, 0.0, 0.0],
}


def _make_bn(tmp_path: Path, monkeypatch) -> BenchmarkNotetaker:
    monkeypatch.delenv("MASE_DB_PATH", raising=False)
    monkeypatch.setenv("MASE_MEMORY_DIR", str(tmp_path))
    monkeypatch.delenv("MASE_EVENT_SEMANTIC_RECALL", raising=False)
    monkeypatch.delenv("MASE_EMBED_MODEL", raising=False)
    return BenchmarkNotetaker()


def _seed_kenji(bn: BenchmarkNotetaker) -> None:
    bn.write(
        user_query="Tell me about your weekends.",
        assistant_response=(
            "Kenji's weekend ritual involves gliding across frozen ponds "
            "with blades strapped to his boots, weaving between the "
            "other neighborhood kids until the light fades."
        ),
        summary="Kenji weekend ritual",
        thread_id="t1",
    )
    bn.write(
        user_query="How do you feel about the cold?",
        assistant_response="Kenji says winter is his least favorite season because of the cold commute.",
        summary="Kenji winter complaint",
        thread_id="t1",
    )
    bn.write(
        user_query="What did you watch last night?",
        assistant_response="Kenji watched a sport documentary about mountain climbing.",
        summary="Kenji sport documentary",
        thread_id="t1",
    )


def _fake_embedder(monkeypatch):
    from mase import event_semantic_recall

    calls: list[list[str]] = []

    def _fake(texts: list[str], *, model: str | None = None) -> list[list[float]]:
        calls.append(list(texts))
        missing = [t for t in texts if t not in _FAKE_VECTORS]
        assert not missing, f"fake embedder has no vector for {missing!r}"
        return [_FAKE_VECTORS[t] for t in texts]

    monkeypatch.setattr(event_semantic_recall, "embed_texts", _fake)
    return calls


class TestEventSemanticRecallDefaultOff:
    def test_default_off_never_embeds_and_ranking_is_unchanged(self, tmp_path, monkeypatch):
        bn = _make_bn(tmp_path, monkeypatch)
        _seed_kenji(bn)

        from mase import event_semantic_recall

        def _boom(*args, **kwargs):
            raise AssertionError("default path must never call the embedder")

        monkeypatch.setattr(event_semantic_recall, "embed_texts", _boom)

        results = bn.search(
            ["Kenji", "winter", "sport"],
            full_query="What winter sport does Kenji practice?",
            limit=1,
        )
        top_content = str(results[0].get("content") or "")
        # Identical to the pinned characterization baseline: a literal decoy wins.
        assert "gliding across frozen ponds" not in top_content


class TestEventSemanticRecallOptIn:
    def test_discovers_associative_needle_missed_by_keywords(self, tmp_path, monkeypatch):
        bn = _make_bn(tmp_path, monkeypatch)
        monkeypatch.setenv("MASE_EVENT_SEMANTIC_RECALL", "1")
        _fake_embedder(monkeypatch)
        _seed_kenji(bn)

        results = bn.search(
            ["Kenji", "winter", "sport"],
            full_query="What winter sport does Kenji practice?",
            limit=1,
        )

        all_content = " ".join(str(r.get("content") or "") for r in results)
        assert "gliding across frozen ponds" in all_content, (
            "Semantic discovery should surface the associative needle as a "
            f"supplemental candidate even though limit=1 is filled by decoys: {results!r}"
        )

    def test_literal_top_result_is_not_displaced(self, tmp_path, monkeypatch):
        """Discovery only appends; it must never outrank/replace a literal hit."""
        bn = _make_bn(tmp_path, monkeypatch)
        monkeypatch.setenv("MASE_EVENT_SEMANTIC_RECALL", "1")
        _fake_embedder(monkeypatch)
        _seed_kenji(bn)

        results = bn.search(
            ["Kenji", "winter", "sport"],
            full_query="What winter sport does Kenji practice?",
            limit=1,
        )
        top_content = str(results[0].get("content") or "")
        assert "gliding across frozen ponds" not in top_content, (
            "The literal top-1 slot must stay exactly what the lexical baseline "
            f"picked; discovery must only add extra candidates: {results!r}"
        )

    def test_semantic_candidate_is_tagged_distinctly(self, tmp_path, monkeypatch):
        bn = _make_bn(tmp_path, monkeypatch)
        monkeypatch.setenv("MASE_EVENT_SEMANTIC_RECALL", "1")
        _fake_embedder(monkeypatch)
        _seed_kenji(bn)

        results = bn.search(
            ["Kenji", "winter", "sport"],
            full_query="What winter sport does Kenji practice?",
            limit=1,
        )
        found = [r for r in results if "gliding across frozen ponds" in str(r.get("content") or "")]
        assert found, "expected the discovered needle in the result set"
        assert found[0].get("retrieval_reason") == "event_semantic_discovery"
        assert found[0].get("confidence") == "low"

    def test_row_vectors_are_cached_across_queries(self, tmp_path, monkeypatch):
        bn = _make_bn(tmp_path, monkeypatch)
        monkeypatch.setenv("MASE_EVENT_SEMANTIC_RECALL", "1")
        calls = _fake_embedder(monkeypatch)
        _seed_kenji(bn)

        bn.search(["Kenji", "winter", "sport"], full_query="What winter sport does Kenji practice?", limit=1)
        first_round_calls = len(calls)
        bn.search(["Kenji", "winter", "sport"], full_query="What winter sport does Kenji practice?", limit=1)
        # Second round: only the query re-embeds; row vectors come from
        # memory_log_embeddings cache.
        assert len(calls) == first_round_calls + 1
        assert calls[-1] == ["What winter sport does Kenji practice?"]

    def test_no_full_query_means_no_discovery_call(self, tmp_path, monkeypatch):
        bn = _make_bn(tmp_path, monkeypatch)
        monkeypatch.setenv("MASE_EVENT_SEMANTIC_RECALL", "1")

        from mase import event_semantic_recall

        def _boom(*args, **kwargs):
            raise AssertionError("discovery must not run without a full_query to embed")

        monkeypatch.setattr(event_semantic_recall, "embed_texts", _boom)
        _seed_kenji(bn)

        # No full_query supplied -> nothing to embed, discovery must no-op.
        bn.search(["Kenji"], limit=1)
