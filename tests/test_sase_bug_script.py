"""Tests for the sase_bug helper script."""

from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "src" / "sase" / "scripts" / "sase_bug"


def test_sase_bug_invokes_canonical_patch_search() -> None:
    text = _SCRIPT.read_text(encoding="utf-8")
    assert "sase patch search" in text
    assert "sase changespec" not in text
