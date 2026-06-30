from __future__ import annotations

import json
import sys
from types import ModuleType

import pytest

from mase import skills_installer as installer


def test_local_install_list_and_uninstall_round_trip(tmp_path, monkeypatch, capsys) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    assert (
        installer.main(
            [
                "install",
                "--agent",
                "codex",
                "--scope",
                "local",
                "--project-root",
                str(project_root),
            ]
        )
        == 0
    )
    target = project_root / ".mase" / "skills" / "mase"
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert (target / "SKILL.md").exists()
    assert manifest["agent"] == "codex"
    assert manifest["scope"] == "local"
    assert manifest["project_root"] == str(project_root.resolve())

    monkeypatch.chdir(project_root)
    assert installer.main(["list"]) == 0
    assert str(target) in capsys.readouterr().out

    assert (
        installer.main(
            [
                "uninstall",
                "--agent",
                "codex",
                "--scope",
                "local",
                "--project-root",
                str(project_root),
            ]
        )
        == 0
    )
    assert not target.exists()

    assert (
        installer.main(
            [
                "uninstall",
                "--agent",
                "codex",
                "--scope",
                "local",
                "--project-root",
                str(project_root),
            ]
        )
        == 0
    )
    assert "nothing at" in capsys.readouterr().out


def test_parser_rejects_unknown_agent() -> None:
    with pytest.raises(SystemExit):
        installer.main(["install", "--agent", "unknown"])


def test_bridge_actions_delegate_to_memory_modules(monkeypatch, capsys) -> None:
    notetaker_module = ModuleType("mase_tools.memory.notetaker")
    notetaker_module.search_recent = lambda query, limit: [{"query": query, "limit": limit}]
    fact_sheet_module = ModuleType("mase_tools.memory.fact_sheet")
    fact_sheet_module.get_fact = lambda key: "Juniper-7"
    upserts: list[tuple[str, str]] = []
    fact_sheet_module.upsert_fact = lambda key, value: upserts.append((key, value))

    monkeypatch.setitem(sys.modules, "mase_tools.memory.notetaker", notetaker_module)
    monkeypatch.setitem(sys.modules, "mase_tools.memory.fact_sheet", fact_sheet_module)

    assert installer.main(["bridge", "search", "--query", "relay", "--limit", "3"]) == 0
    assert json.loads(capsys.readouterr().out)["query"] == "relay"

    assert installer.main(["bridge", "get-fact", "--key", "relay.active"]) == 0
    assert json.loads(capsys.readouterr().out) == {"key": "relay.active", "value": "Juniper-7"}

    assert installer.main(["bridge", "upsert-fact", "--key", "relay.active", "--value", "Alder-4"]) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": True, "key": "relay.active"}
    assert upserts == [("relay.active", "Alder-4")]
