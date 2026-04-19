"""Tests for the real (non-mock) MCP tool implementations."""
from __future__ import annotations

import pytest

from mase_tools.mcp import tools


@pytest.fixture()
def sandbox(tmp_path, monkeypatch):
    (tmp_path / "hello.txt").write_text("hello world", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "inner.txt").write_text("inner", encoding="utf-8")
    monkeypatch.setenv("MASE_MCP_SANDBOX", str(tmp_path))
    return tmp_path


def test_get_current_time_returns_iso_like():
    out = tools.get_current_time()
    # YYYY-MM-DD HH:MM:SS
    assert len(out) == 19 and out[4] == "-" and out[10] == " "


def test_read_local_file_disabled_without_sandbox(monkeypatch):
    monkeypatch.delenv("MASE_MCP_SANDBOX", raising=False)
    assert "disabled" in tools.read_local_file("hello.txt")


def test_read_local_file_reads_file(sandbox):
    assert tools.read_local_file("hello.txt") == "hello world"


def test_read_local_file_blocks_path_traversal(sandbox):
    out = tools.read_local_file("../../../etc/passwd")
    assert "escapes sandbox" in out or "not found" in out or "invalid" in out


def test_read_local_file_size_cap(sandbox, monkeypatch):
    monkeypatch.setattr(tools, "MAX_READ_BYTES", 5)
    out = tools.read_local_file("hello.txt")
    assert "too large" in out


def test_list_directory_returns_entries(sandbox):
    out = tools.list_directory(".")
    assert "hello.txt" in out and "sub/" in out


def test_list_directory_disabled_without_sandbox(monkeypatch):
    monkeypatch.delenv("MASE_MCP_SANDBOX", raising=False)
    assert "disabled" in tools.list_directory(".")
