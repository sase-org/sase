"""Archive restore chooser, fork, and open-chat tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agents._archive_restore import (
    CHOICE_COPY_MORE,
    CHOICE_COPY_REF,
    CHOICE_FORK,
    CHOICE_OPEN_CHAT,
    CHOICE_RESTORE,
    CHOICE_RESTORE_SHOW,
    archive_chooser_model,
    archive_fork_accepted,
    fork_archive_agent,
    open_archive_chat,
    open_archive_chooser,
)
from sase.feature_flags import override_flags
from tests.ace.tui._agent_archive_restore_helpers import (
    make_agent,
    make_owner,
    make_row,
    open_archive,
    wire_bundles,
)

__all__ = [
    "test_chooser_model_defaults_to_restore",
    "test_chooser_model_falls_back_to_open_chat",
    "test_chooser_model_hides_fork_when_unaccepted",
    "test_chooser_model_marks_change_default_label",
    "test_fork_acceptance_rules",
    "test_fork_prefills_prompt",
    "test_open_archive_chat_paths",
    "test_open_chooser_pushes_modal_with_initial",
    "test_open_chooser_unreadable_warns",
]


def test_chooser_model_defaults_to_restore(monkeypatch: Any) -> None:
    owner = make_owner()
    agent = make_agent()
    wire_bundles(monkeypatch, owner, {"u.m@r1": (make_row(), agent, False)})
    model = archive_chooser_model(owner, "u.m@r1")
    assert model is not None
    choices, initial, title = model
    results = [choice.result for choice in choices]
    assert results == [
        CHOICE_RESTORE,
        CHOICE_RESTORE_SHOW,
        CHOICE_FORK,
        CHOICE_OPEN_CHAT,
        CHOICE_COPY_REF,
        CHOICE_COPY_MORE,
    ]
    assert [choice.hotkey for choice in choices] == ["r", "s", "F", "e", "y", "%"]
    assert all(choice.section == "archive" for choice in choices)
    assert initial == 0
    assert choices[0].label == "Restore to inbox"
    assert "archived" in title


def test_chooser_model_falls_back_to_open_chat(monkeypatch: Any) -> None:
    owner = make_owner()
    agent = make_agent(durably_revivable=False)
    wire_bundles(
        monkeypatch, owner, {"u.m@r1": (make_row(restorable=False), agent, False)}
    )
    model = archive_chooser_model(owner, "u.m@r1")
    assert model is not None
    choices, initial, _title = model
    assert CHOICE_RESTORE not in [choice.result for choice in choices]
    assert CHOICE_RESTORE_SHOW not in [choice.result for choice in choices]
    assert choices[initial].result == CHOICE_OPEN_CHAT


def test_chooser_model_hides_fork_when_unaccepted(monkeypatch: Any) -> None:
    owner = make_owner()
    clan = make_agent(is_clan_container=True, is_agent_entry=False, agent_name="")
    wire_bundles(monkeypatch, owner, {"u.m@clan": (make_row("clan"), clan, False)})
    model = archive_chooser_model(owner, "u.m@clan")
    assert model is not None
    choices, _initial, _title = model
    assert CHOICE_FORK not in [choice.result for choice in choices]


def test_chooser_model_marks_change_default_label(monkeypatch: Any) -> None:
    owner = make_owner()
    open_archive(owner)
    agent = make_agent()
    wire_bundles(monkeypatch, owner, {"u.m@r1": (make_row(), agent, False)})
    owner._agents_archive_view.archive.marks = frozenset({"u.m@a1", "u.m@a2"})
    model = archive_chooser_model(owner, "u.m@r1")
    assert model is not None
    choices, _initial, _title = model
    assert choices[0].label == "Restore 2 marked"


def test_open_chooser_unreadable_warns(monkeypatch: Any) -> None:
    owner = make_owner()
    wire_bundles(monkeypatch, owner, {"u.m@r1": (make_row(), make_agent(), True)})
    assert open_archive_chooser(owner, "u.m@r1") is False
    assert owner.pushed == []
    assert owner.notices[0][0] == "Archive entry unreadable — Record only"


def test_open_chooser_pushes_modal_with_initial(monkeypatch: Any) -> None:
    import sase.ace.tui.modals.agent_action_chooser_modal as modal_module

    owner = make_owner()
    agent = make_agent()
    wire_bundles(monkeypatch, owner, {"u.m@r1": (make_row(), agent, False)})
    seen: dict[str, Any] = {}

    class _FakeModal:
        def __init__(self, choices: Any, *, title: str, initial_index: int = 0) -> None:
            seen["count"] = len(tuple(choices))
            seen["title"] = title
            seen["initial"] = initial_index

    monkeypatch.setattr(modal_module, "AgentActionChooserModal", _FakeModal)
    assert open_archive_chooser(owner, "u.m@r1") is True
    assert seen == {"count": 6, "title": "Act on bob-cli-5p.4 · archived", "initial": 0}
    assert len(owner.pushed) == 1


def test_fork_acceptance_rules() -> None:
    assert archive_fork_accepted(make_agent()) is True
    assert (
        archive_fork_accepted(make_agent(is_clan_container=True, is_agent_entry=False))
        is False
    )
    assert (
        archive_fork_accepted(
            make_agent(is_workflow_step_child=True, is_agent_entry=False)
        )
        is False
    )
    assert (
        archive_fork_accepted(
            make_agent(agent_name="", presented_agent_name=None, display_name=None)
        )
        is False
    )
    assert archive_fork_accepted(None) is False


def test_fork_prefills_prompt(monkeypatch: Any) -> None:
    import sase.ace.tui.actions.agents._fork_scope as fork_scope

    owner = make_owner()
    agent = make_agent()
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        fork_scope, "agent_prompt_target_scope", lambda *a, **k: ("scope", a, k)
    )

    def _prepare(scope: Any, *, action: str) -> None:
        captured["scope"] = scope
        captured["action"] = action

    owner._prepare_agent_prompt_target = _prepare  # type: ignore[attr-defined]
    assert fork_archive_agent(owner, agent) is True
    assert captured["action"] == "fork"


def test_open_archive_chat_paths() -> None:
    owner = make_owner()
    opened: list[list[str]] = []
    owner._open_agent_chat_paths = lambda paths: opened.append(list(paths))  # type: ignore[attr-defined]
    assert open_archive_chat(owner, None) is False
    assert open_archive_chat(owner, make_agent(response_path=None)) is False
    assert open_archive_chat(owner, make_agent(response_path="~/chat.md")) is True
    assert opened and opened[0][0].endswith("chat.md")
    assert not opened[0][0].startswith("~")
