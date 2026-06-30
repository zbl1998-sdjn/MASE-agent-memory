from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from benchmarks import baseline, llm_judge, official_source_gap_audit as gap_audit
from mase import __main__ as mase_main
from mase.model_http import ModelHTTPMixin
from mase_tools.cli import __main__ as mase_tools_main
from mase_tools.cli import memory_diff


class DummyHTTP(ModelHTTPMixin):
    def __init__(self) -> None:
        self.fallbacks: dict[str, Any] = {}
        self._http_clients: dict[str, httpx.Client] = {}


def test_memory_diff_snapshot_mode_reports_bucket_summary(tmp_path: Path, capsys) -> None:
    vault = tmp_path / "memory"
    old_context = vault / "snapshots" / "s1" / "context"
    new_context = vault / "snapshots" / "s2" / "context"
    old_context.mkdir(parents=True)
    new_context.mkdir(parents=True)
    (old_context / "relay.json").write_text('{"value": "Alder-4"}\n', encoding="utf-8")
    (new_context / "relay.json").write_text('{"value": "Juniper-7"}\n', encoding="utf-8")
    (vault / "snapshots" / "s2" / "sessions").mkdir(parents=True)
    (vault / "snapshots" / "s2" / "sessions" / "case.json").write_text('{"turns": 1}\n', encoding="utf-8")

    code = memory_diff.run_memory_diff(
        argparse.Namespace(from_ref="s1", to_ref="s2", vault=str(vault))
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "# tri-vault diff (snapshot):" in out
    assert "context: +" in out
    assert "sessions: +" in out
    assert "Juniper-7" in out
    assert memory_diff._is_git_dir(tmp_path / "missing") == (False, None)


def test_memory_diff_missing_vault_and_cli_entrypoint(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "missing"

    assert memory_diff.run_memory_diff(argparse.Namespace(from_ref=None, to_ref=None, vault=str(missing))) == 1
    assert "vault directory does not exist" in capsys.readouterr().err
    assert mase_tools_main.main(["memory", "diff", "--vault", str(missing)]) == 1
    assert "vault directory does not exist" in capsys.readouterr().err


def test_mase_top_level_cli_subcommands(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(mase_main, "validate_config_path", lambda path, strict=False: ({"ok": True}, ["minor warning"]))
    reloaded: list[str | None] = []
    monkeypatch.setattr(mase_main, "reload_system", lambda config: reloaded.append(config))
    assert mase_main.main(["reload-config", "--config", "config.test.json"]) == 0
    assert reloaded == ["config.test.json"]
    assert "config validation warnings" in capsys.readouterr().err

    monkeypatch.setattr(mase_main, "validate_config_path", lambda path, strict=False: (None, ["bad config"]))
    assert mase_main.main(["reload-config"]) == 2
    assert "config validation failed" in capsys.readouterr().err

    class FakeTracker:
        def snapshot(self) -> dict[str, Any]:
            return {"healthy": True}

    class FakeMetrics:
        def snapshot(self) -> dict[str, Any]:
            return {"requests": 2}

        def format_prometheus(self) -> str:
            return "mase_requests 2\n"

    monkeypatch.setattr(mase_main, "get_tracker", lambda: FakeTracker())
    assert mase_main.main(["health"]) == 0
    assert json.loads(capsys.readouterr().out) == {"healthy": True}

    monkeypatch.setattr(mase_main, "get_metrics", lambda: FakeMetrics())
    assert mase_main.main(["metrics"]) == 0
    assert json.loads(capsys.readouterr().out) == {"requests": 2}
    assert mase_main.main(["metrics", "--format", "prometheus"]) == 0
    assert capsys.readouterr().out == "mase_requests 2\n"

    monkeypatch.setattr(mase_main, "migrate_db", lambda db_path: {"applied": 1})
    assert mase_main.main(["migrate-db", "--db", str(tmp_path / "memory.sqlite")]) == 0
    assert json.loads(capsys.readouterr().out)["applied"] == 1

    monkeypatch.setattr(mase_main, "describe_models", lambda config: {"config": config, "models": []})
    assert mase_main.main(["describe-models", "--config", "config.test.json"]) == 0
    assert json.loads(capsys.readouterr().out)["config"] == "config.test.json"

    observed: dict[str, Any] = {}

    def fake_ask(question: str, *, log: bool) -> str:
        observed["question"] = question
        observed["log"] = log
        return "answer"

    monkeypatch.setattr(mase_main, "mase_ask", fake_ask)
    assert mase_main.main(["ask", "Which relay?", "--no-log"]) == 0
    assert capsys.readouterr().out.strip() == "answer"
    assert observed == {"question": "Which relay?", "log": False}


def test_model_http_settings_retry_and_client_reuse(monkeypatch) -> None:
    http = DummyHTTP()
    http.fallbacks = {
        "cloud_timeout_seconds": 30,
        "cloud_connect_timeout_seconds": 2,
        "cloud_max_connections": 4,
        "cloud_retry_count": 0,
        "cloud_retry_base_delay": 1,
        "cloud_retry_max_delay": 5,
        "cloud_retry_jitter": 0.25,
    }

    assert http._is_transient_ollama_error(RuntimeError("Connection refused 10061")) is True
    assert http._is_transient_ollama_error(RuntimeError("bad prompt")) is False

    request = httpx.Request("GET", "https://example.test")
    retry_response = httpx.Response(429, request=request)
    fatal_response = httpx.Response(400, request=request)
    assert http._is_transient_openai_error(httpx.HTTPStatusError("retry", request=request, response=retry_response)) is True
    assert http._is_transient_openai_error(httpx.HTTPStatusError("fatal", request=request, response=fatal_response)) is False
    assert http._is_transient_openai_error(httpx.TimeoutException("timeout")) is True

    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:11434")
    assert http._resolve_ollama_base_url() == "http://127.0.0.1:11434"
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    http.fallbacks["ollama_base_url"] = "https://ollama.test/"
    assert http._resolve_ollama_base_url() == "https://ollama.test"

    timeouts = http._resolve_http_timeout_settings({"timeout": {"overall": 0, "connect": 3}, "read_timeout_seconds": 7})
    assert timeouts == {"overall": 0.1, "connect": 3.0, "read": 7.0, "write": 7.0, "pool": 5.0}
    limits = http._resolve_http_limits_settings({"pool_limits": {"max_connections": 0, "keepalive_expiry": 0}})
    assert limits["max_connections"] == 1
    assert limits["max_keepalive_connections"] == 1
    assert limits["keepalive_expiry"] == 1.0

    retry = http._resolve_http_retry_settings({"retry_count": 0, "retry_backoff_multiplier": 0})
    assert retry["retry_count"] == 1
    assert retry["retry_backoff_multiplier"] == 1.0
    monkeypatch.setattr("mase.model_http.random.uniform", lambda start, stop: 0.2)
    assert http._compute_retry_delay(3, retry) == 1.2

    client1 = http._get_http_client({"http2": False})
    client2 = http._get_http_client({"http2": False})
    assert client1 is client2
    for client in http._http_clients.values():
        client.close()


def test_model_http_wait_for_ollama_ready(monkeypatch) -> None:
    http = DummyHTTP()
    http.fallbacks = {
        "ollama_healthcheck_timeout": 0,
        "ollama_healthcheck_poll_interval": 0.1,
        "ollama_healthcheck_probe_timeout": 0.1,
    }
    monkeypatch.setattr(http, "_probe_ollama_ready", lambda timeout_seconds: False)
    assert http._wait_for_ollama_ready() is False

    http.fallbacks["ollama_healthcheck_timeout"] = 0.01
    monkeypatch.setattr(http, "_probe_ollama_ready", lambda timeout_seconds: True)
    assert http._wait_for_ollama_ready() is True


def test_baseline_models_normalize_and_call_fake_backends(monkeypatch) -> None:
    assert baseline._normalize_message_content({"content": " direct "}) == "direct"
    assert baseline._normalize_message_content({"reasoning_content": "analysis\n最终答案：Juniper-7"}) == "Juniper-7"
    assert baseline._normalize_message_content({"reasoning_content": "plain reasoning"}) == "plain reasoning"
    assert baseline._normalize_message_content({}) == ""
    with pytest.raises(KeyError):
        baseline.BaselineChatModel(profile="missing")

    class FakeOllama:
        def chat(self, **kwargs) -> dict[str, Any]:
            return {"message": {"content": " Juniper-7 "}, "prompt_eval_count": 4}

    monkeypatch.setattr(baseline, "ollama", FakeOllama())
    conversation: list[dict[str, str]] = [{"role": "assistant", "content": "ready"}]
    answer = baseline.baseline_ask(conversation, "Which relay?", system_prompt="system")
    assert answer == "Juniper-7"
    assert conversation[-2:] == [
        {"role": "user", "content": "Which relay?"},
        {"role": "assistant", "content": "Juniper-7"},
    ]

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"choices": [{"message": {"reasoning_content": "最终答案：Alder-4"}}], "usage": {"tokens": 3}}

    class FakeClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def post(self, endpoint: str, *, json: dict[str, Any]) -> FakeResponse:
            assert endpoint.endswith("/chat/completions")
            assert json["model"] == "model-x"
            return FakeResponse()

    monkeypatch.setitem(
        baseline.BASELINE_PROFILES,
        "fake-openai",
        {"provider": "openai_compatible", "model_name": "model-x", "base_url": "https://api.test/v1"},
    )
    monkeypatch.setattr(baseline.httpx, "Client", FakeClient)
    metrics = baseline.baseline_ask_with_metrics([], "Which relay?", profile="fake-openai")
    assert metrics["answer"] == "Alder-4"
    assert metrics["usage"] == {"tokens": 3}

    monkeypatch.setitem(baseline.BASELINE_PROFILES, "bad-provider", {"provider": "bad", "model_name": "bad"})
    with pytest.raises(ValueError):
        baseline.BaselineChatModel("bad-provider").complete_with_metadata([])


def test_official_source_gap_audit_statuses(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        gap_audit,
        "_load_oracle_index",
        lambda: {
            "configured-gap": {"answer": "Rachel and Mike", "haystack_sessions": ["Rachel appears alone."]},
            "retrieval-gap": {"answer": "Rachel and Mike", "haystack_sessions": ["Rachel and Mike both appear."]},
            "recovered-gap": {"answer": "Rachel and Mike", "haystack_sessions": ["Rachel and Mike both appear."]},
        },
    )
    monkeypatch.setitem(
        gap_audit.OFFICIAL_SOURCE_GAPS,
        "configured-gap",
        {"required_markers": ["Rachel and Mike"], "gap_type": "official_source_gap", "reason": "known"},
    )
    monkeypatch.setitem(
        gap_audit.OFFICIAL_SOURCE_GAPS,
        "recovered-gap",
        {"required_markers": ["Rachel and Mike"], "gap_type": "official_source_gap", "reason": "known"},
    )

    case_dir = tmp_path / "case"
    (case_dir / "system").mkdir(parents=True)
    (case_dir / "system" / "ignored.json").write_text("{}", encoding="utf-8")
    (case_dir / "session").mkdir()
    (case_dir / "session" / "old.fact_card.json").write_text("{}", encoding="utf-8")
    (case_dir / "session" / "record.json").write_text(
        json.dumps({"metadata": {"fact_sheet": "Rachel is present."}, "assistant_response": ""}),
        encoding="utf-8",
    )

    assert gap_audit.audit_official_source_gap(
        sample_id="x",
        benchmark="gsm8k",
        ground_truth="Rachel and Mike",
        case_memory_dir=case_dir,
    ) is None
    configured = gap_audit.audit_official_source_gap(
        sample_id="configured-gap",
        benchmark="longmemeval_s",
        ground_truth="Rachel and Mike",
        case_memory_dir=case_dir,
    )
    assert configured and configured["status"] == "data_gap"
    assert configured["missing_from_haystack"] == ["Rachel and Mike"]

    retrieval = gap_audit.audit_official_source_gap(
        sample_id="retrieval-gap",
        benchmark="longmemeval_s",
        ground_truth="Rachel and Mike",
        case_memory_dir=case_dir,
    )
    assert retrieval and retrieval["status"] == "retrieval_gap"
    assert retrieval["missing_from_case_fact_sheet"] == ["Rachel and Mike"]

    (case_dir / "session" / "record.json").write_text(
        json.dumps({"metadata": {"fact_sheet": "Rachel and Mike are both present."}}),
        encoding="utf-8",
    )
    recovered = gap_audit.audit_official_source_gap(
        sample_id="recovered-gap",
        benchmark="longmemeval_s",
        ground_truth="Rachel and Mike",
        case_memory_dir=case_dir,
    )
    assert recovered and recovered["status"] == "recovered"
    assert gap_audit.audit_official_source_gap(
        sample_id="retrieval-gap",
        benchmark="longmemeval_s",
        ground_truth="Rachel and Mike",
        case_memory_dir=case_dir,
    ) is None


def test_llm_judge_parsing_cache_and_score_upgrade(monkeypatch) -> None:
    assert "Question type: temporal" in llm_judge._build_user_prompt("q", "gt", "ans", "temporal")
    assert llm_judge._parse_verdict('{"correct": true, "reason": "ok"}') is True
    assert llm_judge._parse_verdict('{"correct": "false"}') is False
    assert llm_judge._parse_verdict("Yes, correct.") is True
    assert llm_judge._parse_verdict("Incorrect answer.") is False
    assert llm_judge._parse_verdict("unclear") is None

    class FakeInterface:
        def __init__(self) -> None:
            self.calls = 0

        def chat(self, **kwargs) -> dict[str, Any]:
            self.calls += 1
            return {"message": {"content": '{"correct": true, "reason": "same meaning"}'}}

    fake = FakeInterface()
    monkeypatch.setattr(llm_judge, "_JUDGE_INTERFACE", fake)
    llm_judge._JUDGE_CACHE.clear()
    assert llm_judge.judge_answer("q", "gt", "ans", question_type="preference") is True
    assert llm_judge.judge_answer("q", "gt", "ans", question_type="preference") is True
    assert fake.calls == 1
    assert llm_judge.judge_answer("q", "", "ans") is None

    failed = {"score": 0.0, "all_matched": False, "details": {"exact": False}}
    monkeypatch.delenv("MASE_USE_LLM_JUDGE", raising=False)
    assert llm_judge.maybe_upgrade_score(
        failed,
        question="q",
        ground_truth="gt",
        answer="ans",
        question_type=None,
        benchmark="longmemeval_s",
    ) is failed

    monkeypatch.setenv("MASE_USE_LLM_JUDGE", "1")
    upgraded = llm_judge.maybe_upgrade_score(
        failed,
        question="q2",
        ground_truth="gt2",
        answer="ans2",
        question_type=None,
        benchmark="longmemeval_s",
    )
    assert upgraded["all_matched"] is True
    assert upgraded["score"] == 1.0
    assert upgraded["details"]["llm_judge"] == {"verdict": True, "applied": True}
    assert llm_judge.maybe_upgrade_score(
        failed,
        question="q",
        ground_truth="gt",
        answer="I cannot answer",
        question_type=None,
        benchmark="longmemeval_s",
    ) is failed
