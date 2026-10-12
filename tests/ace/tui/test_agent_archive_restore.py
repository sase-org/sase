"""Archive restore, fork, and copy tests (phase sase-1jm.5).

Proves the ⏎ chooser's ARCHIVE section (Restore to inbox by default,
Restore and show, Fork, Open chat, Copy), container and marked bulk restore
with skip reasons, restored rows staying in place behind the ⌂ restored
overlay, ``y`` copying the @agent reference on the Agents tab, and the
``%`` copy-palette targets ported from the pane (! handoff, l link,
j json, d artifacts dir).
"""

from __future__ import annotations

import json
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
    collect_archive_restore_keys,
    fork_archive_agent,
    hydrate_archive_candidate,
    open_archive_chat,
    open_archive_chooser,
    run_archive_restore,
)
from sase.ace.tui.actions.agents._archive_view import init_agents_archive_view_state
from sase.ace.tui.models.agent_archive_view import (
    AGENTS_VIEW_ARCHIVE,
    ARCHIVE_SECTION_LIST,
    ARCHIVE_SECTION_PULSE,
)
from sase.feature_flags import override_flags


def _agent(name: str = "bob-cli-5p.4", **overrides: Any) -> SimpleNamespace:
    fields: dict[str, Any] = {
        "agent_name": name,
        "presented_agent_name": name,
        "display_name": name,
        "cl_name": name,
        "status": "DONE",
        "identity": ("agent", name, None),
        "durably_revivable": True,
        "raw_suffix": "suffix-1",
        "response_path": "/tmp/chat.md",
        "artifacts_dir": "/tmp/artifacts",
        "is_clan_container": False,
        "is_agent_entry": True,
        "is_agent_session_container_row": False,
        "is_workflow_step_child": False,
        "project_display_name": "Test",
        "model": "muse",
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _row(name: str = "bob-cli-5p.4", **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {"agent_name": name, "restorable": True}
    row.update(overrides)
    return row


def _owner() -> SimpleNamespace:
    owner = SimpleNamespace()
    owner.current_tab = "agents"
    owner.notices: list[tuple[str, Any]] = []
    owner.pushed: list[tuple[Any, Any]] = []
    owner._marked_agents = set()

    def notify(message: str, *, severity: str = "information") -> None:
        owner.notices.append((message, severity))

    def push_screen(modal: Any, callback: Any = None) -> None:
        owner.pushed.append((modal, callback))

    owner.notify = notify
    owner.push_screen = push_screen
    init_agents_archive_view_state(owner)
    return owner


def _open_archive(
    owner: SimpleNamespace, *, selected_key: str | None = "u.m@r1"
) -> None:
    owner._agents_archive_view.active_view = AGENTS_VIEW_ARCHIVE
    owner._agents_archive_view.generation += 1
    owner._agents_archive_view.archive.selected_key = selected_key
    owner._agents_archive_view.archive.focused_section = ARCHIVE_SECTION_LIST


def _wire_bundles(
    monkeypatch: Any,
    owner: SimpleNamespace,
    bundles: dict[str, tuple[dict[str, Any], SimpleNamespace | None, bool]],
) -> None:
    """Map archive key -> (light row, hydrated agent, unreadable)."""
    import sase.ace.tui.actions.agents._archive_column as column
    import sase.ace.tui.actions.agents._archive_reader as reader

    rows = {key: row for key, (row, _agent, _bad) in bundles.items()}
    monkeypatch.setattr(column, "archive_light_row", lambda _o, k: rows.get(k))
    monkeypatch.setattr(column, "archive_container_members", lambda _o, _c: ())

    def _bundle(_o: Any, light_row: Any) -> dict[str, Any]:
        for _key, (row, agent, bad) in bundles.items():
            if row is light_row:
                return {
                    "unreadable": bad,
                    "path": "/tmp/bundle.json",
                    "agent": None if bad else agent,
                    "retained": (),
                    "missing": (),
                }
        return {"unreadable": True, "path": None, "agent": None}

    monkeypatch.setattr(reader, "_load_archive_bundle", _bundle)


def _revive_stub(
    owner: SimpleNamespace,
    *,
    revived: tuple[Any, ...] = (),
    failed: tuple[Any, ...] = (),
    calls: list[list[Any]] | None = None,
) -> None:
    def _revive(agents: list[Any]) -> SimpleNamespace:
        if calls is not None:
            calls.append(list(agents))
        return SimpleNamespace(
            revived_identities=tuple(
                getattr(agent, "identity", None) for agent in revived
            ),
            failed=list(failed),
        )

    owner._do_revive_agents = _revive  # type: ignore[attr-defined]


def test_collect_single_row_key() -> None:
    owner = _owner()
    _open_archive(owner)
    with override_flags(agents_archive_view=True):
        keys, skipped = collect_archive_restore_keys(owner)
    assert keys == ["u.m@r1"]
    assert skipped == []


def test_collect_banner_and_pulse_skipped() -> None:
    owner = _owner()
    with override_flags(agents_archive_view=True):
        _open_archive(owner, selected_key="banner:day:2026-10-10")
        keys, skipped = collect_archive_restore_keys(owner)
        assert keys == []
        assert len(skipped) == 1
        assert skipped[0].reason == "not an archived run"
        _open_archive(owner, selected_key="u.m@r1")
        owner._agents_archive_view.archive.focused_section = ARCHIVE_SECTION_PULSE
        keys, skipped = collect_archive_restore_keys(owner)
        assert keys == []
        assert len(skipped) == 1


def test_collect_marked_wins_over_cursor() -> None:
    owner = _owner()
    _open_archive(owner, selected_key="u.m@cursor")
    owner._agents_archive_view.archive.marks = frozenset({"u.m@a1", "u.m@a2"})
    with override_flags(agents_archive_view=True):
        keys, _skipped = collect_archive_restore_keys(owner)
    assert sorted(keys) == ["u.m@a1", "u.m@a2"]


def test_collect_container_expands_loaded_members() -> None:
    from sase.ace.tui.actions.agents._archive_column import _ColumnRuntime
    from sase.ace.tui.models.agent_archive_list import ITEM_CONTAINER, ITEM_MEMBER

    owner = _owner()
    _open_archive(owner, selected_key="container:archive:u.m@clan1")
    member_rows = [
        {
            "archive_key": {
                "source_username": "u",
                "source_machine": "m",
                "source_run_id": "m1",
            },
            "container_key": "archive:u.m@clan1",
            "agent_name": "swarm.one",
        },
        {
            "archive_key": {
                "source_username": "u",
                "source_machine": "m",
                "source_run_id": "m2",
            },
            "container_key": "archive:u.m@clan1",
            "agent_name": "swarm.two",
        },
    ]
    items = [
        SimpleNamespace(kind=ITEM_CONTAINER, member_of=None, row=None),
        *(
            SimpleNamespace(kind=ITEM_MEMBER, member_of="archive:u.m@clan1", row=row)
            for row in member_rows
        ),
    ]
    runtime = _ColumnRuntime()
    runtime.model = SimpleNamespace(items=items)  # type: ignore[assignment]
    owner._archive_column_runtime = runtime
    with override_flags(agents_archive_view=True):
        keys, skipped = collect_archive_restore_keys(owner)
    assert sorted(keys) == ["u.m@m1", "u.m@m2"]
    assert skipped == []


def test_collect_collapsed_container_skipped_with_hint() -> None:
    from sase.ace.tui.actions.agents._archive_column import _ColumnRuntime

    owner = _owner()
    _open_archive(owner, selected_key="container:archive:u.m@clan1")
    runtime = _ColumnRuntime()
    runtime.model = SimpleNamespace(items=[])  # type: ignore[assignment]
    owner._archive_column_runtime = runtime
    with override_flags(agents_archive_view=True):
        keys, skipped = collect_archive_restore_keys(owner)
    assert keys == []
    assert len(skipped) == 1
    assert "expand" in skipped[0].reason


def test_hydrate_capability_rechecked_before_submit(monkeypatch: Any) -> None:
    owner = _owner()
    agent = _agent(durably_revivable=False)
    _wire_bundles(monkeypatch, owner, {"u.m@r1": (_row(), agent, False)})
    with override_flags(agents_archive_view=True):
        found, _row_out, reason = hydrate_archive_candidate(owner, "u.m@r1")
    # The agent is reported so the chooser can still offer Open chat,
    # Fork, and Copy; the reason keeps it out of the restore submission.
    assert found is agent
    assert reason == "can't restore"


def test_hydrate_chip_does_not_block_revivable_bundle(monkeypatch: Any) -> None:
    owner = _owner()
    agent = _agent()
    _wire_bundles(
        monkeypatch,
        owner,
        {
            "u.m@chip": (_row(restorable=False), agent, False),
            "u.m@bad": (_row(), _agent(), True),
        },
    )
    with override_flags(agents_archive_view=True):
        # A stale corpus chip never blocks a revivable bundle: the hydrated
        # agent's capability decides just before submitting.
        found, _r1, reason = hydrate_archive_candidate(owner, "u.m@chip")
        assert found is agent
        assert reason is None
        found, _r2, reason = hydrate_archive_candidate(owner, "u.m@bad")
        assert found is None
        assert reason == "bundle unreadable"


def test_run_single_restore_marks_overlay_and_toasts(monkeypatch: Any) -> None:
    owner = _owner()
    _open_archive(owner)
    agent = _agent()
    _wire_bundles(monkeypatch, owner, {"u.m@r1": (_row(), agent, False)})
    _revive_stub(owner, revived=(agent,))
    with override_flags(agents_archive_view=True):
        summary = run_archive_restore(owner)
    assert [name for _key, name in summary.restored] == ["bob-cli-5p.4"]
    assert summary.skipped == ()
    assert summary.failed == ()
    assert "u.m@r1" in owner._agents_archive_view.archive.restored_keys
    assert owner.notices == [
        ("bob-cli-5p.4 is back in the inbox · no new run started", "information")
    ]
    # The cursor never jumps: the row stays in the Archive.
    assert owner._agents_archive_view.active_view == AGENTS_VIEW_ARCHIVE
    assert owner._agents_archive_view.archive.selected_key == "u.m@r1"


def test_run_bulk_reports_counts_with_reasons(monkeypatch: Any) -> None:
    owner = _owner()
    _open_archive(owner, selected_key="u.m@good")
    good = _agent("good.run")
    locked = _agent("locked.run", durably_revivable=False)
    _wire_bundles(
        monkeypatch,
        owner,
        {
            "u.m@good": (_row("good.run"), good, False),
            "u.m@locked": (_row("locked.run", restorable=False), locked, False),
            "u.m@bad": (_row("gone.run"), _agent("gone.run"), True),
        },
    )
    owner._agents_archive_view.archive.marks = frozenset(
        {"u.m@good", "u.m@locked", "u.m@bad"}
    )
    calls: list[list[Any]] = []
    _revive_stub(owner, revived=(good,), calls=calls)
    with override_flags(agents_archive_view=True):
        summary = run_archive_restore(owner)
    assert len(calls) == 1 and calls[0] == [good]
    assert [name for _key, name in summary.restored] == ["good.run"]
    assert len(summary.skipped) == 2
    assert len(owner.notices) == 1
    message, severity = owner.notices[0]
    assert message.startswith("Restored 1 · skipped 2 (")
    assert "can't restore" in message
    assert "bundle unreadable" in message
    assert "failed 0" in message
    assert severity == "information"


def test_run_failed_rows_reported_without_overlay(monkeypatch: Any) -> None:
    owner = _owner()
    _open_archive(owner)
    agent = _agent()
    _wire_bundles(monkeypatch, owner, {"u.m@r1": (_row(), agent, False)})
    failure = SimpleNamespace(
        identity=agent.identity, agent_name=agent.agent_name, message="disk is gone"
    )
    _revive_stub(owner, failed=(failure,))
    with override_flags(agents_archive_view=True):
        summary = run_archive_restore(owner)
    assert summary.restored == ()
    assert summary.failed == (("u.m@r1", "bob-cli-5p.4", "disk is gone"),)
    assert "u.m@r1" not in owner._agents_archive_view.archive.restored_keys
    message, severity = owner.notices[0]
    assert "Restored 0" in message
    assert severity == "warning"


def test_run_restore_and_show_reveals_in_inbox(monkeypatch: Any) -> None:
    owner = _owner()
    _open_archive(owner)
    agent = _agent()
    _wire_bundles(monkeypatch, owner, {"u.m@r1": (_row(), agent, False)})
    _revive_stub(owner, revived=(agent,))
    owner._select_revived_agent = lambda _agent: True  # type: ignore[attr-defined]
    refreshed: list[bool] = []
    owner._refresh_agents_display = lambda **_kwargs: refreshed.append(True)  # type: ignore[attr-defined]
    with override_flags(agents_archive_view=True):
        summary = run_archive_restore(owner, and_show=True)
    assert summary.and_show is True
    assert owner._agents_archive_view.active_view != AGENTS_VIEW_ARCHIVE
    assert refreshed == [True]
    assert owner.notices == [
        ("bob-cli-5p.4 is back in the inbox · showing in Inbox", "information")
    ]


def test_run_restore_and_show_filter_hidden_warns(monkeypatch: Any) -> None:
    owner = _owner()
    _open_archive(owner)
    agent = _agent()
    _wire_bundles(monkeypatch, owner, {"u.m@r1": (_row(), agent, False)})
    _revive_stub(owner, revived=(agent,))
    owner._select_revived_agent = lambda _agent: False  # type: ignore[attr-defined]
    owner._agents_with_children = [agent]  # type: ignore[attr-defined]
    with override_flags(agents_archive_view=True):
        run_archive_restore(owner, and_show=True)
    assert owner.notices == [
        (
            "bob-cli-5p.4 is back in the inbox · the inbox filter hides it",
            "warning",
        )
    ]


def test_run_restore_and_show_reload_pending_stays_neutral(
    monkeypatch: Any,
) -> None:
    owner = _owner()
    _open_archive(owner)
    agent = _agent()
    _wire_bundles(monkeypatch, owner, {"u.m@r1": (_row(), agent, False)})
    _revive_stub(owner, revived=(agent,))
    owner._select_revived_agent = lambda _agent: False  # type: ignore[attr-defined]
    owner._agents_with_children = []  # type: ignore[attr-defined]
    with override_flags(agents_archive_view=True):
        run_archive_restore(owner, and_show=True)
    assert owner.notices == [
        ("bob-cli-5p.4 is back in the inbox · no new run started", "information")
    ]


def test_chooser_model_defaults_to_restore(monkeypatch: Any) -> None:
    owner = _owner()
    agent = _agent()
    _wire_bundles(monkeypatch, owner, {"u.m@r1": (_row(), agent, False)})
    with override_flags(agents_archive_view=True):
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
    owner = _owner()
    agent = _agent(durably_revivable=False)
    _wire_bundles(
        monkeypatch, owner, {"u.m@r1": (_row(restorable=False), agent, False)}
    )
    with override_flags(agents_archive_view=True):
        model = archive_chooser_model(owner, "u.m@r1")
    assert model is not None
    choices, initial, _title = model
    assert CHOICE_RESTORE not in [choice.result for choice in choices]
    assert CHOICE_RESTORE_SHOW not in [choice.result for choice in choices]
    assert choices[initial].result == CHOICE_OPEN_CHAT


def test_chooser_model_hides_fork_when_unaccepted(monkeypatch: Any) -> None:
    owner = _owner()
    clan = _agent(is_clan_container=True, is_agent_entry=False, agent_name="")
    _wire_bundles(monkeypatch, owner, {"u.m@clan": (_row("clan"), clan, False)})
    with override_flags(agents_archive_view=True):
        model = archive_chooser_model(owner, "u.m@clan")
    assert model is not None
    choices, _initial, _title = model
    assert CHOICE_FORK not in [choice.result for choice in choices]


def test_chooser_model_marks_change_default_label(monkeypatch: Any) -> None:
    owner = _owner()
    _open_archive(owner)
    agent = _agent()
    _wire_bundles(monkeypatch, owner, {"u.m@r1": (_row(), agent, False)})
    owner._agents_archive_view.archive.marks = frozenset({"u.m@a1", "u.m@a2"})
    with override_flags(agents_archive_view=True):
        model = archive_chooser_model(owner, "u.m@r1")
    assert model is not None
    choices, _initial, _title = model
    assert choices[0].label == "Restore 2 marked"


def test_open_chooser_unreadable_warns(monkeypatch: Any) -> None:
    owner = _owner()
    _wire_bundles(monkeypatch, owner, {"u.m@r1": (_row(), _agent(), True)})
    with override_flags(agents_archive_view=True):
        assert open_archive_chooser(owner, "u.m@r1") is False
    assert owner.pushed == []
    assert owner.notices[0][0] == "Archive entry unreadable — Record only"


def test_open_chooser_pushes_modal_with_initial(monkeypatch: Any) -> None:
    import sase.ace.tui.modals.agent_action_chooser_modal as modal_module

    owner = _owner()
    agent = _agent()
    _wire_bundles(monkeypatch, owner, {"u.m@r1": (_row(), agent, False)})
    seen: dict[str, Any] = {}

    class _FakeModal:
        def __init__(self, choices: Any, *, title: str, initial_index: int = 0) -> None:
            seen["count"] = len(tuple(choices))
            seen["title"] = title
            seen["initial"] = initial_index

    monkeypatch.setattr(modal_module, "AgentActionChooserModal", _FakeModal)
    with override_flags(agents_archive_view=True):
        assert open_archive_chooser(owner, "u.m@r1") is True
    assert seen == {"count": 6, "title": "Act on bob-cli-5p.4 · archived", "initial": 0}
    assert len(owner.pushed) == 1


def test_fork_acceptance_rules() -> None:
    assert archive_fork_accepted(_agent()) is True
    assert (
        archive_fork_accepted(_agent(is_clan_container=True, is_agent_entry=False))
        is False
    )
    assert (
        archive_fork_accepted(_agent(is_workflow_step_child=True, is_agent_entry=False))
        is False
    )
    assert (
        archive_fork_accepted(
            _agent(agent_name="", presented_agent_name=None, display_name=None)
        )
        is False
    )
    assert archive_fork_accepted(None) is False


def test_fork_prefills_prompt(monkeypatch: Any) -> None:
    import sase.ace.tui.actions.agents._fork_scope as fork_scope

    owner = _owner()
    agent = _agent()
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
    owner = _owner()
    opened: list[list[str]] = []
    owner._open_agent_chat_paths = lambda paths: opened.append(list(paths))  # type: ignore[attr-defined]
    assert open_archive_chat(owner, None) is False
    assert open_archive_chat(owner, _agent(response_path=None)) is False
    assert open_archive_chat(owner, _agent(response_path="~/chat.md")) is True
    assert opened and opened[0][0].endswith("chat.md")
    assert not opened[0][0].startswith("~")


def test_y_copies_agent_reference_on_agents_tab(monkeypatch: Any) -> None:
    import sase.ace.tui.actions.clipboard._agents as agents_clipboard
    from sase.ace.tui.actions.clipboard._agents import ClipboardAgentsMixin
    from sase.ace.tui.actions.clipboard._artifacts import ClipboardArtifactsMixin

    copied: dict[str, Any] = {}
    monkeypatch.setattr(
        agents_clipboard,
        "schedule_copy_delivery",
        lambda _o, content, **kwargs: copied.update(content=content, kwargs=kwargs),
    )
    monkeypatch.setattr(
        agents_clipboard, "reference_for_agent_row", lambda _agent: "test.1"
    )

    class App(ClipboardArtifactsMixin, ClipboardAgentsMixin):
        pass

    app = App()
    agent = _agent()
    app.__dict__.update(
        {
            "current_tab": "agents",
            "current_artifacts_pane_key": "agents",
            "_inbox_agent": agent,
            "notify": lambda *a, **k: None,
            "_get_selected_agent": lambda: agent,
        }
    )
    init_agents_archive_view_state(app)
    with override_flags(agents_archive_view=True):
        app.action_artifacts_copy_reference()
    assert copied.get("content") == "@test.1"


def test_copy_palette_new_targets_dispatch(monkeypatch: Any) -> None:
    from sase.ace.tui.actions.clipboard._core import ClipboardCoreMixin

    handled: list[str] = []

    class App(ClipboardCoreMixin):
        pass

    app = App()
    app.__dict__.update(
        {
            "_keymap_registry": SimpleNamespace(
                copy_mode=SimpleNamespace(
                    keys={
                        "agents": {
                            "chat": "c",
                            "file_path": "E",
                            "name": "n",
                            "prompt": "p",
                            "reference": "at",
                            "handoff": "!",
                            "link": "l",
                            "json": "j",
                            "artifacts_dir": "d",
                            "tool_run_id": "r",
                            "snapshot": "s",
                        }
                    }
                )
            ),
            "notify": lambda *a, **k: None,
        }
    )
    for target in ("handoff", "link", "json", "artifacts_dir"):
        monkeypatch.setattr(
            App,
            f"_copy_agent_{target}",
            lambda self, _t=target: handled.append(_t),
            raising=False,
        )
    for key, target in (
        ("!", "handoff"),
        ("l", "link"),
        ("j", "json"),
        ("d", "artifacts_dir"),
    ):
        assert app._handle_agents_copy_key(key) is True
    assert handled == ["handoff", "link", "json", "artifacts_dir"]


def test_copy_link_format_is_followable(monkeypatch: Any) -> None:
    import sase.ace.tui.actions.clipboard._agents as agents_clipboard
    from sase.ace.tui.actions.clipboard._agents import ClipboardAgentsMixin

    copied: dict[str, Any] = {}
    monkeypatch.setattr(
        agents_clipboard,
        "schedule_copy_delivery",
        lambda _o, content, **kwargs: copied.update(content=content),
    )
    monkeypatch.setattr(
        agents_clipboard, "reference_for_agent_row", lambda _agent: "test.1"
    )

    class App(ClipboardAgentsMixin):
        pass

    app = App()
    agent = _agent()
    app.__dict__.update(
        {
            "notify": lambda *a, **k: None,
            "_get_selected_agent": lambda: agent,
        }
    )
    init_agents_archive_view_state(app)
    with override_flags(agents_archive_view=True):
        app._copy_agent_link()
    assert copied.get("content") == "[@test.1](agent:test.1)"


def test_copy_json_payload_is_metadata(monkeypatch: Any) -> None:
    import sase.ace.tui.actions.clipboard._agents as agents_clipboard
    from sase.ace.tui.actions.clipboard._agents import ClipboardAgentsMixin

    copied: dict[str, Any] = {}
    monkeypatch.setattr(
        agents_clipboard,
        "schedule_copy_delivery",
        lambda _o, content, **kwargs: copied.update(content=content),
    )

    class App(ClipboardAgentsMixin):
        pass

    app = App()
    app.__dict__.update(
        {
            "notify": lambda *a, **k: None,
            "_get_selected_agent": lambda: _agent(),
        }
    )
    init_agents_archive_view_state(app)
    with override_flags(agents_archive_view=True):
        app._copy_agent_json()
    payload = json.loads(copied["content"])
    assert payload["agent_name"] == "bob-cli-5p.4"
    assert payload["status"] == "DONE"


def test_copy_artifacts_dir_missing_warns() -> None:
    from sase.ace.tui.actions.clipboard._agents import ClipboardAgentsMixin

    class App(ClipboardAgentsMixin):
        pass

    app = App()
    notices: list[str] = []
    app.__dict__.update(
        {
            "notify": lambda message, **_k: notices.append(message),
            "_get_selected_agent": lambda: _agent(artifacts_dir=None),
        }
    )
    init_agents_archive_view_state(app)
    with override_flags(agents_archive_view=True):
        app._copy_agent_artifacts_dir()
    assert notices == ["Selected agent has no artifacts directory"]


def test_copy_handoff_prefills_prompt(monkeypatch: Any) -> None:
    import sase.ace.tui.actions.clipboard._agents as agents_clipboard
    from sase.ace.tui.actions.clipboard._agents import ClipboardAgentsMixin

    monkeypatch.setattr(
        agents_clipboard, "reference_for_agent_row", lambda _agent: "test.1"
    )

    class App(ClipboardAgentsMixin):
        pass

    app = App()
    prompted: dict[str, Any] = {}
    app.__dict__.update(
        {
            "notify": lambda *a, **k: None,
            "_get_selected_agent": lambda: _agent(),
            "_show_prompt_input_bar_for_home": lambda **kwargs: prompted.update(kwargs),
        }
    )
    init_agents_archive_view_state(app)
    with override_flags(agents_archive_view=True):
        app._copy_agent_handoff()
    assert prompted.get("initial_text") == "@test.1 "


def test_footer_offers_restore_without_live_chips() -> None:
    from sase.ace.tui.widgets._keybinding_bindings_agents import AgentBindingsMixin

    mixin = AgentBindingsMixin()
    mixin._kd = lambda name: name  # type: ignore[attr-defined]
    bindings = mixin._compute_archive_bindings(
        marked_count=0,
        has_selection=True,
        selection_is_container=False,
    )
    assert ("act_on_agent", "restore…") in bindings
    text = " ".join(f"{key} {label}" for key, label in bindings)
    for live in ("kill", "wait", "retry", "cleanup", "tabs", "Inbox"):
        assert live not in text


def test_help_archive_box_lists_action_rows() -> None:
    from sase.ace.tui.keymaps import load_keymap_registry
    from sase.ace.tui.modals.help_modal.agents_archive_sections import archive_sections

    km = load_keymap_registry({})
    boxes = dict(archive_sections(km))
    rows = boxes["Archive (read-only)"]
    assert rows[0][0] == ",a"
    assert all(len(key) <= 16 for key, _description in rows)
    assert all(len(description) <= 32 for _key, description in rows)
    descriptions = [description for _key, description in rows]
    assert "Restore archived run" in descriptions
    assert "Open archived chat" in descriptions
    assert "Fork archived run" in descriptions
    assert "Copy @agent: reference" in descriptions
    assert "More copy targets" in descriptions
