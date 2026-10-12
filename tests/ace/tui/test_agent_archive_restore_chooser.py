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
    "test_chooser_model_container_restore_label",
    "test_chooser_model_defaults_to_restore",
    "test_chooser_model_falls_back_to_open_chat",
    "test_chooser_model_hides_fork_when_unaccepted",
    "test_chooser_model_hides_fork_without_retained_chat",
    "test_chooser_model_marks_change_default_label",
    "test_chooser_model_marks_with_unrestorable_cursor",
    "test_chooser_model_opens_when_unreadable_cursor_has_marks",
    "test_chooser_model_session_container_restore_label",
    "test_fork_acceptance_rules",
    "test_fork_prefills_prompt",
    "test_open_archive_chat_paths",
    "test_open_chooser_pushes_modal_with_initial",
    "test_open_chooser_unreadable_warns",
    "test_open_chooser_uses_captured_agent",
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
    assert [choice.section for choice in choices] == [
        "archive",
        "archive",
        "archive",
        "read",
        "read",
        "read",
    ]
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


def test_chooser_model_container_restore_label(monkeypatch: Any) -> None:
    owner = make_owner()
    open_archive(owner, selected_key="container:clan:swarm:1")
    row = make_row("swarm", member_count=3)
    wire_bundles(monkeypatch, owner, {"container:clan:swarm:1": (row, None, False)})
    model = archive_chooser_model(owner, "container:clan:swarm:1")
    assert model is not None
    choices, initial, title = model
    results = [choice.result for choice in choices]
    assert results == [CHOICE_RESTORE, CHOICE_RESTORE_SHOW]
    assert choices[0].label == "Restore clan swarm (3 members)"
    assert initial == 0
    assert "swarm" in title


def test_chooser_model_session_container_restore_label(monkeypatch: Any) -> None:
    owner = make_owner()
    open_archive(owner, selected_key="container:session:alpha")
    row = make_row("alpha", member_count=1)
    wire_bundles(monkeypatch, owner, {"container:session:alpha": (row, None, False)})
    model = archive_chooser_model(owner, "container:session:alpha")
    assert model is not None
    choices, _initial, _title = model
    assert choices[0].label == "Restore session alpha (1 member)"


def test_chooser_model_marks_with_unrestorable_cursor(monkeypatch: Any) -> None:
    owner = make_owner()
    open_archive(owner)
    agent = make_agent(durably_revivable=False)
    wire_bundles(
        monkeypatch, owner, {"u.m@r1": (make_row(restorable=False), agent, False)}
    )
    owner._agents_archive_view.archive.marks = frozenset({"u.m@a1", "u.m@a2"})
    model = archive_chooser_model(owner, "u.m@r1")
    assert model is not None
    choices, initial, _title = model
    assert choices[0].label == "Restore 2 marked"
    assert initial == 0
    assert CHOICE_OPEN_CHAT in [choice.result for choice in choices]


def test_chooser_model_opens_when_unreadable_cursor_has_marks(
    monkeypatch: Any,
) -> None:
    owner = make_owner()
    open_archive(owner)
    wire_bundles(monkeypatch, owner, {"u.m@r1": (make_row(), make_agent(), True)})
    owner._agents_archive_view.archive.marks = frozenset({"u.m@a1"})
    model = archive_chooser_model(owner, "u.m@r1")
    assert model is not None
    choices, initial, _title = model
    assert choices[0].label == "Restore 1 marked"
    assert initial == 0
    assert CHOICE_OPEN_CHAT not in [choice.result for choice in choices]


def test_chooser_model_hides_fork_without_retained_chat(monkeypatch: Any) -> None:
    owner = make_owner()
    agent = make_agent(response_path=None)
    wire_bundles(monkeypatch, owner, {"u.m@r1": (make_row(), agent, False)})
    model = archive_chooser_model(owner, "u.m@r1")
    assert model is not None
    choices, _initial, _title = model
    assert CHOICE_FORK not in [choice.result for choice in choices]


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
    assert archive_fork_accepted(make_agent(response_path=None)) is False
    retained = make_agent(response_path=None)
    retained.get_response_content = lambda: "hello"
    assert archive_fork_accepted(retained) is True
    assert archive_fork_accepted(None) is False


def test_open_chooser_uses_captured_agent(monkeypatch: Any) -> None:
    import sase.ace.tui.actions.agents._archive_restore_entry as entry
    import sase.ace.tui.modals.agent_action_chooser_modal as modal_module

    owner = make_owner()
    agent = make_agent()
    wire_bundles(monkeypatch, owner, {"u.m@r1": (make_row(), agent, False)})
    seen: dict[str, Any] = {}

    class _FakeModal:
        def __init__(self, choices: Any, *, title: str, initial_index: int = 0) -> None:
            seen["count"] = len(tuple(choices))

    monkeypatch.setattr(modal_module, "AgentActionChooserModal", _FakeModal)
    forked: list[Any] = []
    monkeypatch.setattr(
        entry, "fork_archive_agent", lambda _owner, target: forked.append(target)
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._archive_actions.archive_read_target",
        lambda _owner: None,
    )
    assert open_archive_chooser(owner, "u.m@r1") is True
    _modal, callback = owner.pushed[0]
    callback(CHOICE_FORK)
    assert forked == [agent]


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
