"""Tests for the bundled ``#coder`` xprompt body."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.sdd import plan_refs
from sase.xprompt.processor import process_xprompt_references

_TARGET_SENTENCE = (
    "The 202608/accept_command_line_tools.md plan file has been reviewed and "
    "approved. Implement it now."
)


def _flatten(expanded: str) -> str:
    return " ".join(expanded.split())


def test_coder_names_a_canonical_plan_reference_without_inlining() -> None:
    expanded = process_xprompt_references(
        "#coder(plan:202608/accept_command_line_tools.md)"
    )
    assert _flatten(expanded) == _TARGET_SENTENCE
    assert "@" not in expanded


def test_coder_names_an_archive_path_without_inlining(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "plans"
    plan = root / "202608" / "accept_command_line_tools.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Plan\n", encoding="utf-8")
    monkeypatch.setattr(plan_refs, "resolve_plan_roots", lambda *_: (root,))

    expanded = process_xprompt_references(f"#coder:{plan}")
    assert _flatten(expanded) == _TARGET_SENTENCE
    assert "@" not in expanded


def test_coder_passes_through_a_non_plan_path_unchanged(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch.md"

    expanded = process_xprompt_references(f"#coder:{scratch}")

    assert _flatten(expanded) == (
        f"The {scratch} plan file has been reviewed and approved. Implement it now."
    )
    assert "@" not in expanded
