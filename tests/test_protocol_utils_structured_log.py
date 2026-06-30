from __future__ import annotations

import io
import json
import logging
from pathlib import Path

from mase.event_bus import get_bus, publish
from mase.protocol import AgentMessage, make_message
from mase.structured_log import configure, get_logger
from mase.utils import memory_root, normalize_json_text


def test_make_message_defaults_metadata_and_serializes() -> None:
    msg = make_message(
        kind="task",
        source="router",
        target="executor",
        payload={"question": "Which relay is active?"},
        thread_id="thread-1",
    )

    assert isinstance(msg, AgentMessage)
    assert msg.metadata == {}
    assert msg.created_at.endswith("+00:00")
    assert msg.to_dict() == {
        "kind": "task",
        "source": "router",
        "target": "executor",
        "payload": {"question": "Which relay is active?"},
        "thread_id": "thread-1",
        "metadata": {},
        "created_at": msg.created_at,
    }


def test_make_message_keeps_explicit_metadata() -> None:
    metadata = {"trace_id": "trace-1"}

    msg = make_message(
        kind="result",
        source="executor",
        target="router",
        payload={"answer": "Juniper-7"},
        metadata=metadata,
    )

    assert msg.metadata == metadata
    assert msg.thread_id is None


def test_normalize_json_text_extracts_fenced_and_embedded_objects() -> None:
    assert normalize_json_text('```json\n{"answer": "Juniper-7"}\n```') == {"answer": "Juniper-7"}
    assert normalize_json_text('prefix {"score": 1, "ok": true} suffix') == {"score": 1, "ok": True}
    assert normalize_json_text("[1, 2, 3]") is None
    assert normalize_json_text("not json") is None
    assert normalize_json_text('{"broken":') is None


def test_memory_root_prefers_env_and_creates_directory(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "isolated-memory"
    monkeypatch.setenv("MASE_MEMORY_DIR", str(target))

    resolved = memory_root()

    assert resolved == target.resolve()
    assert resolved.is_dir()


def test_structured_log_configure_outputs_json_once_and_replaces_subscription() -> None:
    pattern = "mase.coverage.structured"
    logger_name = "mase.coverage.structured"
    stream = io.StringIO()
    logger = logging.getLogger(logger_name)
    logger.handlers.clear()

    class NonSerializable:
        pass

    try:
        configure(stream=stream, pattern=pattern, logger_name=logger_name)
        configure(stream=stream, pattern=pattern, logger_name=logger_name)

        publish(
            f"{pattern}.done",
            {"nested": {"ok": True}, "bad": NonSerializable()},
            trace_id="trace-structured",
        )

        lines = [line for line in stream.getvalue().splitlines() if line.strip()]
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert row["topic"] == f"{pattern}.done"
        assert row["trace_id"] == "trace-structured"
        assert row["nested"] == {"ok": True}
        assert "NonSerializable" in row["bad"]
        assert get_logger(logger_name) is logger
    finally:
        get_bus().unsubscribe_all(pattern)
        logger.handlers.clear()
