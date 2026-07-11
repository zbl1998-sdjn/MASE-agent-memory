"""LLM 相关性判定模块:缓存/并行/契约(fake transport,零真模型调用)。"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _p in (_ROOT / "src", _ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _isolate(tmp_path, monkeypatch):
    monkeypatch.delenv("MASE_MEMORY_DIR", raising=False)
    monkeypatch.setenv("MASE_DB_PATH", str(tmp_path / "judge.db"))
    monkeypatch.delenv("MASE_RELEVANCE_JUDGE_MODEL", raising=False)
    monkeypatch.delenv("MASE_RELEVANCE_JUDGE_WORKERS", raising=False)


class _FakeResponse:
    def __init__(self, content: str):
        self._content = content

    def raise_for_status(self):
        pass

    def json(self):
        return {"message": {"content": self._content}}


def _fake_post(monkeypatch, replies_by_snippet: dict[str, str]):
    """按 Snippet 内容路由回复;记录调用与并发峰值。"""
    from mase import relevance_judge

    calls: list[str] = []
    lock = threading.Lock()
    live = {"now": 0, "peak": 0}

    def _post(url, json=None, timeout=None):
        user_msg = json["messages"][1]["content"]
        snippet = user_msg.split("Snippet: ", 1)[1].split("\n", 1)[0]
        with lock:
            live["now"] += 1
            live["peak"] = max(live["peak"], live["now"])
            calls.append(snippet)
        try:
            reply = replies_by_snippet.get(snippet, "ANSWER: no")
            return _FakeResponse(reply)
        finally:
            with lock:
                live["now"] -= 1

    monkeypatch.setattr(relevance_judge.httpx, "post", _post)
    return calls, live


class TestJudgeBatch:
    def test_batch_returns_aligned_verdicts(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        from mase.relevance_judge import judge_relevance_batch

        _fake_post(monkeypatch, {
            "true needle text": "Reasoned it out. ANSWER: yes",
            "wrong needle text": "ANSWER: no",
            "unrelated text": "answer: no",
        })
        verdicts = judge_relevance_batch("q?", ["true needle text", "wrong needle text", "unrelated text"])
        assert verdicts == [True, False, False]

    def test_cache_skips_repeat_judgments(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        from mase.relevance_judge import judge_relevance_batch

        calls, _live = _fake_post(monkeypatch, {"text a": "ANSWER: yes", "text b": "ANSWER: no"})
        first = judge_relevance_batch("q?", ["text a", "text b"])
        assert len(calls) == 2
        second = judge_relevance_batch("q?", ["text a", "text b"])
        assert len(calls) == 2  # 全部缓存命中,零新调用
        assert first == second == [True, False]

    def test_cache_is_query_scoped(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        from mase.relevance_judge import judge_relevance_batch

        calls, _live = _fake_post(monkeypatch, {"text a": "ANSWER: yes"})
        judge_relevance_batch("q1?", ["text a"])
        judge_relevance_batch("q2?", ["text a"])  # 不同 query 不共享判定
        assert len(calls) == 2

    def test_parallel_workers_run_concurrently(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        from mase.relevance_judge import judge_relevance_batch

        gate = threading.Barrier(4, timeout=10)
        from mase import relevance_judge

        lock = threading.Lock()
        live = {"now": 0, "peak": 0}

        def _post(url, json=None, timeout=None):
            with lock:
                live["now"] += 1
                live["peak"] = max(live["peak"], live["now"])
            gate.wait()  # 4 路必须同时在场才能过闸
            with lock:
                live["now"] -= 1
            return _FakeResponse("ANSWER: no")

        monkeypatch.setattr(relevance_judge.httpx, "post", _post)
        judge_relevance_batch("q?", [f"t{i}" for i in range(4)], max_workers=4)
        assert live["peak"] == 4  # 客户端并发确实到位(服务端吞吐另测)

    def test_empty_texts_no_calls(self, tmp_path, monkeypatch):
        _isolate(tmp_path, monkeypatch)
        from mase.relevance_judge import judge_relevance_batch

        calls, _live = _fake_post(monkeypatch, {})
        assert judge_relevance_batch("q?", []) == []
        assert calls == []

    def test_qwen3_requests_thinking(self, tmp_path, monkeypatch):
        """探针实证:无思考 PAIR 2/6,thinking 6/6——qwen3 系必须带 think。"""
        _isolate(tmp_path, monkeypatch)
        from mase import relevance_judge
        from mase.relevance_judge import judge_relevance_batch

        seen_bodies: list[dict] = []

        def _post(url, json=None, timeout=None):
            seen_bodies.append(json)
            return _FakeResponse("ANSWER: no")

        monkeypatch.setattr(relevance_judge.httpx, "post", _post)
        judge_relevance_batch("q?", ["t"])
        assert seen_bodies[0]["model"] == "qwen3:14b"
        assert seen_bodies[0]["think"] is True
        assert seen_bodies[0]["options"]["temperature"] == 0
