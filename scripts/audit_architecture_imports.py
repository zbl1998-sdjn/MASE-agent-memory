"""Audit MASE enterprise architecture import boundaries.

This script checks the stable local boundaries that exist in this repository
today.  It is intentionally static and deterministic so it can run in CI
without importing application modules.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "mase"

FORBIDDEN_IMPORTS: dict[str, tuple[str, ...]] = {
    "mase.contracts": (
        "fastapi",
        "integrations",
        "mase.governance",
        "mase_tools",
    ),
    "mase.core": (
        "fastapi",
        "integrations",
        "mase.governance",
        "mase_tools",
    ),
    "mase.storage.interfaces": (
        "fastapi",
        "integrations",
        "mase.governance",
        "mase_tools",
    ),
    "mase.governance": (
        "fastapi",
        "integrations",
        "mase.api",
        "mase.cli",
    ),
}


@dataclass(frozen=True)
class Violation:
    """A single forbidden import finding."""

    module: str
    path: Path
    line: int
    imported: str
    rule: str


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="Return non-zero when violations are found.")
    args = parser.parse_args(argv)

    violations = audit_imports()
    if violations:
        print("ARCHITECTURE_IMPORT_AUDIT_FAILED")
        for item in violations:
            rel = item.path.relative_to(ROOT)
            print(f"{rel}:{item.line}: {item.module} imports {item.imported} (rule={item.rule})")
    else:
        print("ARCHITECTURE_IMPORT_AUDIT_OK")
    return 1 if args.strict and violations else 0


def audit_imports() -> list[Violation]:
    """Return all forbidden import violations."""
    violations: list[Violation] = []
    for path in SRC.rglob("*.py"):
        module = _module_name(path)
        rules = _rules_for(module)
        if not rules:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            violations.append(Violation(module, path, int(exc.lineno or 1), "<syntax-error>", "parse"))
            continue
        for node in ast.walk(tree):
            imported = _import_name(node)
            if imported is None:
                continue
            for forbidden in rules:
                if imported == forbidden or imported.startswith(f"{forbidden}."):
                    violations.append(Violation(module, path, int(getattr(node, "lineno", 1)), imported, forbidden))
    return violations


def _rules_for(module: str) -> tuple[str, ...]:
    matched: list[str] = []
    for prefix, forbidden in FORBIDDEN_IMPORTS.items():
        if module == prefix or module.startswith(f"{prefix}."):
            matched.extend(forbidden)
    return tuple(dict.fromkeys(matched))


def _module_name(path: Path) -> str:
    rel = path.relative_to(ROOT / "src").with_suffix("")
    parts = rel.parts
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _import_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Import):
        return str(node.names[0].name)
    if isinstance(node, ast.ImportFrom):
        if node.level:
            return None
        return str(node.module or "")
    return None


if __name__ == "__main__":
    raise SystemExit(main())
