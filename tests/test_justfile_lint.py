from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_lint_uses_sdd_validation_not_top_level_validate() -> None:
    justfile = (ROOT / "Justfile").read_text()

    assert "@just _lint-sdd" in justfile
    assert "just _lint-sdd" in justfile
    assert "@just validate" not in justfile
    assert '"SASE validation"     just validate' not in justfile
