"""Tests for the Agents-tab tribe modal action entry points (``N`` keymap)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.modals.agent_tribe_modal import AgentTribeModal
from tests.ace.tui._agent_tribe_assignment_helpers import _FakeApp, _make_agent


def test_action_no_op_when_not_on_agents_tab(tmp_path: Path) -> None:
    app = _FakeApp([_make_agent()])
    app.current_tab = "patches"
    with patch(
        "sase.ace.agent_tribes._AGENT_TRIBES_FILE",
        tmp_path / "agent_tribes.json",
    ):
        app.action_edit_agent_tribe()
    assert app.pushed_modals == []


def test_action_warns_when_no_agent_selected(tmp_path: Path) -> None:
    app = _FakeApp([])
    app.current_idx = -1
    with patch(
        "sase.ace.agent_tribes._AGENT_TRIBES_FILE",
        tmp_path / "agent_tribes.json",
    ):
        app.action_edit_agent_tribe()
    assert app.pushed_modals == []
    assert any("No agent selected" in m for m, _ in app.notifications)


def test_action_pushes_modal_for_focused_agent(tmp_path: Path) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    tribe_file.write_text(
        json.dumps(
            [
                {"id": ["run", "fix-bug", "ts-other"], "tribe": "alpha"},
                {"id": ["run", "fix-bug", "ts-other2"], "tribe": "beta"},
            ]
        )
    )
    agent = _make_agent()
    agent.tribe = "primary"
    app = _FakeApp([agent])
    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file):
        app.action_edit_agent_tribe()
    assert len(app.pushed_modals) == 1
    modal = app.pushed_modals[0]
    assert isinstance(modal, AgentTribeModal)
    assert modal._target_label == agent.display_name
    assert modal._current_tribe == "primary"
    assert modal._known_tribes == ("alpha", "beta")


def test_action_seeds_pinned_for_focused_agent_without_tribe(tmp_path: Path) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    agent = _make_agent()
    assert agent.tribe is None
    app = _FakeApp([agent])
    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file):
        app.action_edit_agent_tribe()
    modal = app.pushed_modals[0]
    assert isinstance(modal, AgentTribeModal)
    assert modal._current_tribe is None
    assert modal._default_tribe == "pinned"


def test_action_does_not_seed_pinned_for_bulk_path(tmp_path: Path) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    a1 = _make_agent(suffix="t1")
    a2 = _make_agent(suffix="t2")
    app = _FakeApp([a1, a2])
    app._marked_agents = {a1.identity, a2.identity}
    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file):
        app.action_edit_agent_tribe()
    modal = app.pushed_modals[0]
    assert isinstance(modal, AgentTribeModal)
    assert modal._default_tribe is None


def test_modal_names_clan_for_single_clan_target(tmp_path: Path) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    member = _make_agent(agent_clan="research", clan_tribe="old")
    app = _FakeApp([member])
    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file):
        app.action_edit_agent_tribe()
    modal = app.pushed_modals[0]
    assert isinstance(modal, AgentTribeModal)
    assert modal._target_label == "clan research"
    assert modal._current_tribe == "old"


def test_modal_names_clan_for_bulk_clan_targets(tmp_path: Path) -> None:
    tribe_file = tmp_path / "agent_tribes.json"
    a1 = _make_agent(suffix="t1", agent_clan="research", clan_tribe="old")
    a2 = _make_agent(suffix="t2", agent_clan="research", clan_tribe="old")
    app = _FakeApp([a1, a2])
    app._marked_agents = {a1.identity, a2.identity}
    with patch("sase.ace.agent_tribes._AGENT_TRIBES_FILE", tribe_file):
        app.action_edit_agent_tribe()
    modal = app.pushed_modals[0]
    assert isinstance(modal, AgentTribeModal)
    assert modal._target_label == "clan research (2 members)"


def test_modal_returns_normalized_result_via_validation() -> None:
    """Validation rejects '@'-prefixed input from the modal layer."""
    from sase.ace.agent_tribes import InvalidTribeError, validate_tribe_name

    try:
        validate_tribe_name("@bad")
    except InvalidTribeError as exc:
        assert "must not start with '@'" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected InvalidTribeError")
