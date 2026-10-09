"""Spelling contract: every ``%auto`` spelling through real launch and gates.

Each row runs ``extract_prompt_directives`` + ``build_agent_meta`` (real
launch), then real tale, epic, and question gate specs through
``create_gate``. Invalid spellings must fail at launch on every column.
"""

from __future__ import annotations

import pytest

from sase.core.agent_launch_facade import plan_typed_launch_units
from sase.core.rust import require_rust_binding
from sase.macro._exceptions import DirectiveError
from sase.macro.directives import extract_prompt_directives

from . import harness
from .rows import INVALID_PROMPTS, SPELLING_ROWS
from tests.plan_validation_helpers import VALID_EPIC_PLAN, VALID_TALE_PLAN


@pytest.mark.parametrize("row", SPELLING_ROWS, ids=[row.id for row in SPELLING_ROWS])
def test_spelling_row(row, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The contract row's three gate outcomes hold through real code."""
    harness.isolated_gate_dirs(monkeypatch, tmp_path)
    workdir = tmp_path / "work"
    workdir.mkdir()
    tale_plan = harness.write_plan_file(workdir, "tale.md", VALID_TALE_PLAN)
    epic_plan = harness.write_plan_file(workdir, "epic.md", VALID_EPIC_PLAN)

    outcomes = harness.row_outcomes(
        row.prompt, workdir, tale_plan, epic_plan, monkeypatch=monkeypatch
    )

    assert outcomes == {"tale": row.tale, "epic": row.epic, "question": row.question}


@pytest.mark.parametrize("prompt", INVALID_PROMPTS)
def test_invalid_spellings_fail_at_launch(prompt: str) -> None:
    """Invalid ``%auto`` spellings fail closed before any gate exists."""
    with pytest.raises(DirectiveError, match="Invalid %auto spelling"):
        extract_prompt_directives(prompt)
    with pytest.raises(ValueError, match="Invalid %auto spelling"):
        plan_typed_launch_units(prompt, selected_project="sase")


@pytest.mark.parametrize("row", SPELLING_ROWS, ids=[row.id for row in SPELLING_ROWS])
def test_spelling_parity_python_rust(row) -> None:
    """Python and the Rust typed launch planner agree on every spelling."""
    _, directives = extract_prompt_directives(row.prompt)
    plan = plan_typed_launch_units(row.prompt, selected_project="sase")
    payload = plan.units[0].payload
    assert payload.auto_enabled is directives.auto_enabled
    assert payload.auto_mode == directives.auto_mode


def test_auto_suggestion_vocabulary_matches_core() -> None:
    """Folded from ``tests/test_auto_grammar_parity.py``: no assertion lost."""
    from sase.macro._directive_types import AUTO_COMPATIBILITY_ARGUMENT_SUGGESTIONS

    vocabulary = require_rust_binding("auto_directive_vocabulary")()
    assert tuple(vocabulary["modes"]) == ("plan", "tale", "epic")
    assert tuple(vocabulary["manual_values"]) == ("manual", "off")
    assert AUTO_COMPATIBILITY_ARGUMENT_SUGGESTIONS == tuple(
        vocabulary["modes"]
    ) + tuple(vocabulary["manual_values"])


def test_auto_duplicate_rejected_on_both_sides() -> None:
    """Folded from ``tests/test_auto_grammar_parity.py``: no assertion lost."""
    with pytest.raises(DirectiveError, match="Duplicate directive '%auto'"):
        extract_prompt_directives("%auto\n%auto:off\nDo the work")
    with pytest.raises(ValueError, match="Only one %auto directive"):
        plan_typed_launch_units(
            "%auto\n%auto:off\nDo the work", selected_project="sase"
        )


def test_live_meta_is_only_auto_source(tmp_path, monkeypatch) -> None:
    """Folded from ``tests/test_plan_auto_live_meta.py``: env never decides."""
    from sase.main.plan_approve_handler import (
        get_auto_plan_approval_action,
        is_auto_approve_active,
    )

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text('{"name": "agent-x"}')
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_AGENT_AUTO_APPROVE", "1")

    assert get_auto_plan_approval_action() is None
    assert is_auto_approve_active() is False
