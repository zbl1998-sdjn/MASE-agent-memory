"""MASE IDE skill installer.

Usage::

    python -m mase.skills_installer install --agent copilot          # global scope
    python -m mase.skills_installer install --agent claude --scope local
    python -m mase.skills_installer list
    python -m mase.skills_installer uninstall --agent copilot

Drops a SKILL.md + small bridge stub into the host AI agent's skills
directory so the agent can discover MASE memory operations
(search/upsert/audit) without each user wiring their own prompt.

Inspired by JimmyMcBride/brain's ``brain skills install`` UX.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

SKILL_NAME = "mase"

SKILL_MD = """---
name: mase
description: |
  MASE long-term memory layer. Use this skill when the user asks the agent to
  remember preferences, recall past conversations, search prior notes, correct
  earlier facts, or work across multiple sessions. MASE provides:
  - SQLite FTS5 full-text search over conversation history
  - An entity fact_sheet (key/value upserts) for stable user/project state
  - Markdown audit logs (one per day) for transparent diffs
  - UPDATE/DELETE supersede semantics so old facts can be retired
triggers:
  - "remember"
  - "记住"
  - "what did I say"
  - "我之前说过"
  - "recall"
  - "回忆"
---

# MASE Memory Skill

When activated:

1. To **search past conversations** call::

     python -m mase.skills_installer bridge search --query "<keywords>"

2. To **read or update a fact** call::

     python -m mase.skills_installer bridge get-fact --key user.diet
     python -m mase.skills_installer bridge upsert-fact --key user.diet --value "vegetarian"

3. To **see today's audit log** read::

     memory/sessions/{today}.md   # tri-vault layout
     memory/logs/{today}.md       # legacy layout

The skill writes nothing without an explicit user-confirmed action.
"""


def _agent_skill_dir(agent: str, scope: str, project_root: Path) -> Path:
    """Return the directory that should hold the SKILL.md for *agent*."""
    home = Path.home()
    if scope == "local":
        return project_root / ".mase" / "skills" / SKILL_NAME
    if agent == "copilot":
        return home / ".copilot" / "skills" / SKILL_NAME
    if agent == "codex":
        return home / ".codex" / "skills" / SKILL_NAME
    if agent == "claude":
        return home / ".claude" / "skills" / SKILL_NAME
    if agent == "cursor":
        return home / ".cursor" / "skills" / SKILL_NAME
    raise SystemExit(f"unknown agent: {agent}")


def cmd_install(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root or os.getcwd()).resolve()
    target = _agent_skill_dir(args.agent, args.scope, project_root)
    target.mkdir(parents=True, exist_ok=True)
    skill_md = target / "SKILL.md"
    skill_md.write_text(SKILL_MD, encoding="utf-8")
    manifest = target / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "name": SKILL_NAME,
                "version": "0.4.0",
                "agent": args.agent,
                "scope": args.scope,
                "project_root": str(project_root),
                "entry": "python -m mase.skills_installer bridge",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[mase.skills] installed to {target}")
    return 0


def cmd_uninstall(args: argparse.Namespace) -> int:
    project_root = Path(args.project_root or os.getcwd()).resolve()
    target = _agent_skill_dir(args.agent, args.scope, project_root)
    if target.exists():
        shutil.rmtree(target)
        print(f"[mase.skills] removed {target}")
    else:
        print(f"[mase.skills] nothing at {target}")
    return 0


def cmd_list(_: argparse.Namespace) -> int:
    home = Path.home()
    candidates = [
        home / ".copilot" / "skills" / SKILL_NAME,
        home / ".codex" / "skills" / SKILL_NAME,
        home / ".claude" / "skills" / SKILL_NAME,
        home / ".cursor" / "skills" / SKILL_NAME,
        Path.cwd() / ".mase" / "skills" / SKILL_NAME,
    ]
    for c in candidates:
        marker = "✓" if c.exists() else " "
        print(f"  [{marker}] {c}")
    return 0


def cmd_bridge(args: argparse.Namespace) -> int:
    """Thin shim — delegate to MASE memory APIs in-process so host agent
    can call this without booting the whole executor."""
    if args.action == "search":
        from mase_tools.memory.notetaker import search_recent  # type: ignore

        for row in search_recent(args.query, limit=args.limit):
            print(json.dumps(row, ensure_ascii=False))
        return 0
    if args.action == "get-fact":
        from mase_tools.memory.fact_sheet import get_fact  # type: ignore

        v = get_fact(args.key)
        print(json.dumps({"key": args.key, "value": v}, ensure_ascii=False))
        return 0
    if args.action == "upsert-fact":
        from mase_tools.memory.fact_sheet import upsert_fact  # type: ignore

        upsert_fact(args.key, args.value)
        print(json.dumps({"ok": True, "key": args.key}, ensure_ascii=False))
        return 0
    raise SystemExit(f"unknown bridge action: {args.action}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mase.skills_installer")
    sub = p.add_subparsers(dest="cmd", required=True)

    install = sub.add_parser("install", help="install MASE skill into a host AI agent")
    install.add_argument("--agent", required=True, choices=["copilot", "codex", "claude", "cursor"])
    install.add_argument("--scope", default="global", choices=["global", "local"])
    install.add_argument("--project-root", default=None)
    install.set_defaults(func=cmd_install)

    uninstall = sub.add_parser("uninstall")
    uninstall.add_argument("--agent", required=True, choices=["copilot", "codex", "claude", "cursor"])
    uninstall.add_argument("--scope", default="global", choices=["global", "local"])
    uninstall.add_argument("--project-root", default=None)
    uninstall.set_defaults(func=cmd_uninstall)

    sub.add_parser("list", help="list installed MASE skills").set_defaults(func=cmd_list)

    bridge = sub.add_parser("bridge", help="(internal) called by host agent")
    bridge.add_argument("action", choices=["search", "get-fact", "upsert-fact"])
    bridge.add_argument("--query", default="")
    bridge.add_argument("--key", default="")
    bridge.add_argument("--value", default="")
    bridge.add_argument("--limit", type=int, default=10)
    bridge.set_defaults(func=cmd_bridge)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
