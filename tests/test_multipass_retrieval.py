from __future__ import annotations

from typing import Any

from mase import multipass_retrieval as mp


class FakeNotetaker:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def search(
        self,
        keywords: list[str],
        *,
        full_query: str | None = None,
        limit: int = 5,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        self.calls.append(
            {
                "keywords": list(keywords),
                "full_query": full_query,
                "limit": limit,
                "kwargs": dict(kwargs),
            }
        )
        if keywords == ["variant query"]:
            return [
                {"id": 1, "score": 0.9, "summary": "variant duplicate wins"},
                {"id": 3, "score": 0.8, "summary": "variant-only"},
            ]
        if keywords == ["failing variant"]:
            raise RuntimeError("search branch failed")
        if keywords == ["hyde", "terms"]:
            return [{"id": 4, "score": 0.7, "summary": "hyde-only"}]
        return [
            {"id": 1, "score": 0.3, "summary": "baseline duplicate"},
            {"id": 2, "score": 0.4, "summary": "baseline-only"},
            {"id": 5, "score": 0.2, "summary": "baseline-tail"},
            {"id": 6, "score": 0.1, "summary": "baseline-tail-2"},
        ]


def test_disabled_multipass_returns_limited_baseline(monkeypatch) -> None:
    monkeypatch.delenv("MASE_MULTIPASS", raising=False)
    notetaker = FakeNotetaker()

    rows = mp.multipass_search(
        notetaker,
        keywords=["relay"],
        full_query="Which relay is active?",
        limit=2,
        search_kwargs={"scope": "current"},
    )

    assert [row["id"] for row in rows] == [1, 2]
    assert notetaker.calls == [
        {
            "keywords": ["relay"],
            "full_query": "Which relay is active?",
            "limit": 5,
            "kwargs": {"scope": "current"},
        }
    ]


def test_enabled_multipass_merges_variants_hyde_and_keeps_best_duplicate(monkeypatch) -> None:
    monkeypatch.setenv("MASE_MULTIPASS", "1")
    monkeypatch.setenv("MASE_MULTIPASS_VARIANTS", "bad-int")
    monkeypatch.setenv("MASE_MULTIPASS_HYDE", "yes")
    monkeypatch.setenv("MASE_MULTIPASS_RERANK", "0")
    monkeypatch.setattr(mp, "_generate_query_variants_cached", lambda question, n: ("variant query", "failing variant"))
    monkeypatch.setattr(mp, "_generate_hyde_keywords_cached", lambda question: ("hyde", "terms"))
    notetaker = FakeNotetaker()

    rows = mp.multipass_search(
        notetaker,
        keywords=["relay"],
        full_query="Which relay is active?",
        limit=3,
    )

    assert [row["id"] for row in rows] == [1, 3, 4]
    assert rows[0]["summary"] == "variant duplicate wins"
    assert [call["keywords"] for call in notetaker.calls] == [
        ["relay"],
        ["variant query"],
        ["failing variant"],
        ["hyde", "terms"],
    ]


def test_rerank_divergence_keeps_baseline_front_guard(monkeypatch) -> None:
    monkeypatch.setenv("MASE_MULTIPASS", "1")
    monkeypatch.setenv("MASE_MULTIPASS_VARIANTS", "0")
    monkeypatch.setenv("MASE_MULTIPASS_HYDE", "0")
    monkeypatch.setenv("MASE_MULTIPASS_RERANK", "1")
    monkeypatch.setenv("MASE_MULTIPASS_RERANK_TOP", "4")
    monkeypatch.setattr(
        mp,
        "_rerank_cross_encoder",
        lambda question, candidates, top_k: [
            {"id": 99, "score": 1.0, "summary": "rerank-only"},
            {"id": 98, "score": 0.9, "summary": "rerank-only-2"},
        ],
    )
    notetaker = FakeNotetaker()

    rows = mp.multipass_search(
        notetaker,
        keywords=["relay"],
        full_query="Which relay is active?",
        limit=4,
    )

    assert [row["id"] for row in rows] == [1, 2, 99, 98]


def test_multisession_routing_uses_larger_rerank_pool(monkeypatch) -> None:
    observed: dict[str, int] = {}
    monkeypatch.setenv("MASE_MULTIPASS", "1")
    monkeypatch.setenv("MASE_MULTIPASS_VARIANTS", "0")
    monkeypatch.setenv("MASE_MULTIPASS_HYDE", "0")
    monkeypatch.setenv("MASE_MULTIPASS_RERANK", "1")
    monkeypatch.setenv("MASE_MULTIPASS_RERANK_TOP", "2")
    monkeypatch.setenv("MASE_LME_QTYPE_ROUTING", "true")
    monkeypatch.setenv("MASE_QTYPE", "multi-session")
    monkeypatch.setenv("MASE_MULTIPASS_RERANK_TOP_MULTISESSION", "17")

    def fake_rerank(question: str, candidates: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
        observed["top_k"] = top_k
        return list(candidates)

    monkeypatch.setattr(mp, "_rerank_cross_encoder", fake_rerank)

    rows = mp.multipass_search(FakeNotetaker(), ["relay"], "Which relay is active?", limit=2)

    assert observed["top_k"] == 17
    assert [row["id"] for row in rows] == [2, 1]
