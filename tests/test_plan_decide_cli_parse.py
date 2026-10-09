"""``-D/--decide`` parsing and submitted-value validation.

Split from ``tests.test_plan_decide_cli``: covers
``parse_decide_assignments``, the toggle/choice submitted-value checks,
the agent-boundary rules, and the ``verdict_for_kind``/format helpers.
Shared fixtures live in ``tests._plan_decide_cli_shared``.
"""

from __future__ import annotations

import pytest

from sase.main.plan_decide import (
    DecideError,
    already_approved_decide_error,
    parse_decide_assignments,
    verdict_for_kind,
)
from tests._plan_decide_cli_shared import make_definitions


def test_parse_decide_assignments_split_id_value() -> None:
    assert parse_decide_assignments(["grouping=mode", "tui_note = yes"]) == {
        "grouping": "mode",
        "tui_note": "yes",
    }


def test_parse_decide_rejects_missing_equals() -> None:
    with pytest.raises(DecideError, match="ID=VALUE"):
        parse_decide_assignments(["grouping"])


def test_parse_decide_rejects_empty_id() -> None:
    with pytest.raises(DecideError):
        parse_decide_assignments(["=mode"])


def test_parse_decide_rejects_duplicate_id() -> None:
    with pytest.raises(DecideError, match="twice"):
        parse_decide_assignments(["grouping=pane", "grouping=mode"])


def test_toggle_accepts_shared_bool_spellings() -> None:
    from sase.main.plan_decide import _build_decide_submitted

    definitions = make_definitions()
    for raw, expected in (
        ("true", True),
        ("1", True),
        ("yes", True),
        ("on", True),
        ("TRUE", True),
        ("false", False),
        ("0", False),
        ("no", False),
        ("off", False),
    ):
        submitted = _build_decide_submitted(
            definitions, {"tui_note": raw}, caller="human"
        )
        assert submitted == {"tui_note": expected}


def test_toggle_rejects_unknown_spelling_with_allowed_values() -> None:
    from sase.main.plan_decide import _build_decide_submitted

    definitions = make_definitions()
    with pytest.raises(DecideError) as excinfo:
        _build_decide_submitted(definitions, {"tui_note": "maybe"}, caller="human")
    assert "bad value" in excinfo.value.header
    assert any("★" in line for line in excinfo.value.detail_lines)


def test_choice_matches_case_insensitively() -> None:
    from sase.main.plan_decide import _build_decide_submitted

    definitions = make_definitions()
    submitted = _build_decide_submitted(
        definitions, {"grouping": "MODE"}, caller="human"
    )
    assert submitted == {"grouping": "mode"}


def test_choice_rejects_prefix_match_with_starred_allowed() -> None:
    from sase.main.plan_decide import _build_decide_submitted

    definitions = make_definitions()
    with pytest.raises(DecideError) as excinfo:
        _build_decide_submitted(definitions, {"grouping": "mod"}, caller="human")
    assert "bad value" in excinfo.value.header
    allowed = " ".join(excinfo.value.detail_lines)
    assert "pane ★" in allowed
    assert "mode" in allowed


def test_unknown_id_suggests_close_match() -> None:
    from sase.main.plan_decide import _build_decide_submitted

    definitions = make_definitions()
    with pytest.raises(DecideError) as excinfo:
        _build_decide_submitted(definitions, {"groupin": "mode"}, caller="human")
    assert "grouping" in excinfo.value.header


def test_agent_memory_switch_on_is_refused() -> None:
    from sase.main.plan_decide import _build_decide_submitted

    definitions = make_definitions()
    with pytest.raises(DecideError, match="only be switched on by a human"):
        _build_decide_submitted(definitions, {"tui_note": "yes"}, caller="agent")


def test_agent_memory_switch_off_passes() -> None:
    from sase.main.plan_decide import _build_decide_submitted

    definitions = make_definitions()
    assert _build_decide_submitted(definitions, {"tui_note": "no"}, caller="agent") == {
        "tui_note": False
    }


def test_already_approved_refusal_names_decide_ids() -> None:
    error = already_approved_decide_error({"tui_note": "yes"})
    assert "already approved" in error.header
    assert "accepted answers" in error.header
    assert "tui_note" in error.header


def test_verdict_for_kind() -> None:
    assert verdict_for_kind("tale") == "coder + commit"
    assert verdict_for_kind(None) == "coder + commit"
    assert verdict_for_kind("approve") == "coder"
    assert verdict_for_kind("commit") == "commit"
    assert verdict_for_kind("epic") == "epic launch"


def test_format_values_sentence_uses_display_words() -> None:
    from sase.main.plan_decide import _format_values_sentence

    assert (
        _format_values_sentence({"grouping": "mode", "tui_note": False})
        == "grouping=mode; tui_note=no"
    )
