"""Audit public API docstring coverage for stable enterprise modules."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGETS = (
    ROOT / "src" / "mase" / "contracts",
    ROOT / "src" / "mase" / "core",
    ROOT / "src" / "mase" / "storage",
    ROOT / "src" / "mase" / "governance",
)


@dataclass(frozen=True)
class PublicObject:
    """A public class/function that should carry an operator-facing docstring."""

    path: Path
    line: int
    name: str
    kind: str
    has_docstring: bool


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true", help="Fail below the required coverage.")
    parser.add_argument("--min-coverage", type=float, default=0.90)
    args = parser.parse_args(argv)

    objects = collect_public_objects(DEFAULT_TARGETS)
    total = len(objects)
    documented = sum(1 for item in objects if item.has_docstring)
    coverage = (documented / total) if total else 1.0
    missing = [item for item in objects if not item.has_docstring]
    print(f"PUBLIC_API_DOCSTRING_COVERAGE={coverage:.3f} documented={documented} total={total}")
    if missing:
        print("PUBLIC_API_DOCSTRING_MISSING")
        for item in missing:
            rel = item.path.relative_to(ROOT)
            print(f"{rel}:{item.line}: {item.kind} {item.name}")
    return 1 if args.strict and coverage < args.min_coverage else 0


def collect_public_objects(targets: tuple[Path, ...]) -> list[PublicObject]:
    """Collect public top-level classes/functions and public methods."""
    objects: list[PublicObject] = []
    for target in targets:
        if not target.exists():
            continue
        for path in target.rglob("*.py"):
            if path.name == "__init__.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in tree.body:
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and _public(node.name):
                    objects.append(_object(path, node, "function"))
                elif isinstance(node, ast.ClassDef) and _public(node.name):
                    objects.append(_object(path, node, "class"))
                    for child in node.body:
                        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) and _public(child.name):
                            objects.append(_object(path, child, f"method {node.name}."))
    return objects


def _object(path: Path, node: ast.AST, kind: str) -> PublicObject:
    return PublicObject(
        path=path,
        line=int(getattr(node, "lineno", 1)),
        name=str(getattr(node, "name", "")),
        kind=kind,
        has_docstring=ast.get_docstring(node) is not None,
    )


def _public(name: str) -> bool:
    return not name.startswith("_")


if __name__ == "__main__":
    raise SystemExit(main())
