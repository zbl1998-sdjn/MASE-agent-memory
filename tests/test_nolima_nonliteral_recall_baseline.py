"""Characterization test: pins BenchmarkNotetaker.search()'s current behavior
on NoLiMa-style non-literal (associative) queries, before any semantic-recall
work lands on the event-log path.

NoLiMa's onehop/twohop/hard tiers deliberately avoid literal keyword overlap
between the question and the needle sentence (e.g. a needle describing an
activity without naming it, and a question asking for the sport/hobby it
implies). ``search()`` today is BM25 + Python term-overlap + fuzzy CJK only
(see src/mase/benchmark_notetaker.py and src/mase/hybrid_recall.py — the
"dense" component of HybridReranker reuses this same lexical score, there is
no embedding step anywhere on this path). Committed evidence
(NOLIMA_3WAY.md / mase-hardening-backlog memory) already shows 0% on the
non-literal tiers at the full-benchmark level; this test pins the same
failure mode at the unit level with a minimal, non-adversarial example so it
can be re-run cheaply during development of a semantic-recall lane, instead
of round-tripping through the full external NoLiMa harness.

This is a characterization test, not a spec: once event-path semantic
discovery lands (opt-in), a companion test should assert the *new* behavior
with the flag on, while this test keeps documenting the default-off floor.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
for _p in (_SRC, _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from mase.benchmark_notetaker import BenchmarkNotetaker


def _make_bn(tmp_path: Path, monkeypatch) -> BenchmarkNotetaker:
    monkeypatch.delenv("MASE_DB_PATH", raising=False)
    monkeypatch.setenv("MASE_MEMORY_DIR", str(tmp_path))
    return BenchmarkNotetaker()


class TestNonLiteralRecallBaseline:
    def test_associative_needle_loses_to_literal_decoys(self, tmp_path, monkeypatch):
        """Needle and question share only the anchor name, no other tokens;
        decoys share literal query tokens but are the wrong answer.

        This mirrors NoLiMa's actual construction (and the documented LV-Eval
        embedding failure mode, mase-hardening-backlog memory) at the lexical
        layer: the true needle describes ice skating without ever saying
        "ice", "skate", "skating", "winter", or "sport"; two decoys use those
        exact words in an unrelated sense. A purely lexical/BM25+term-overlap
        search (src/mase/benchmark_notetaker.py — HybridReranker's "dense"
        component reuses this same lexical score, there is no embedding step
        on this path) scores token overlap, so it should rank a decoy above
        the true needle at top_k=1 — mirroring NoLiMa's committed 0% on the
        non-literal tiers.
        """
        bn = _make_bn(tmp_path, monkeypatch)
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

        results = bn.search(
            ["Kenji", "winter", "sport"],
            full_query="What winter sport does Kenji practice?",
            limit=1,
        )

        assert results, "search should return at least one candidate"
        top_content = str(results[0].get("content") or "")
        assert "gliding across frozen ponds" not in top_content, (
            "Expected the current lexical-only baseline to rank a literal "
            f"decoy above the true associative needle at top_k=1, got: {results!r}"
        )

    def test_literal_needle_is_still_recalled(self, tmp_path, monkeypatch):
        """Sanity check: the same harness *does* find a literally-worded needle.

        Guards against the associative-miss test above passing for the wrong
        reason (e.g. search() broken outright rather than lexical-only).
        """
        bn = _make_bn(tmp_path, monkeypatch)
        bn.write(
            user_query="Tell me about your weekends.",
            assistant_response="Kenji goes ice skating every weekend with the neighborhood kids.",
            summary="Kenji weekend ritual",
            thread_id="t1",
        )

        results = bn.search(
            ["Kenji", "skating"],
            full_query="What winter sport does Kenji practice?",
            limit=5,
        )

        recalled_texts = " ".join(str(r.get("content") or "") for r in results)
        assert "ice skating" in recalled_texts
