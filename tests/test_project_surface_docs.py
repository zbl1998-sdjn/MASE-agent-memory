from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_architecture_boundary_doc_is_linked_and_named() -> None:
    boundary_doc = _read("docs/ARCHITECTURE_BOUNDARIES.md")
    readme = _read("README.md")
    legacy = _read("LEGACY_SHIMS.md")

    assert "Stable Core" in boundary_doc
    assert "Compatibility Surface" in boundary_doc
    assert "Experimental Surface" in boundary_doc
    assert "ARCHITECTURE_BOUNDARIES.md" in readme
    assert "ARCHITECTURE_BOUNDARIES.md" in legacy


def test_experimental_surface_lists_all_required_bullets() -> None:
    boundary_doc = _read("docs/ARCHITECTURE_BOUNDARIES.md")

    assert "experimental benchmark scripts" in boundary_doc
    assert "unpublished config profiles" in boundary_doc
    assert "local generated benchmark artifacts" in boundary_doc
