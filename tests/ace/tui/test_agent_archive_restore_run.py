"""Archive restore collection, hydration, and run tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agents._archive_restore import (
    collect_archive_restore_keys,
    hydrate_archive_candidate,
    run_archive_restore,
)
from sase.ace.tui.models.agent_archive_view import (
    AGENTS_VIEW_ARCHIVE,
    ARCHIVE_SECTION_PULSE,
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
    "test_collect_banner_and_pulse_skipped",
    "test_collect_collapsed_container_skipped_with_hint",
    "test_collect_container_expands_loaded_members",
    "test_collect_marked_wins_over_cursor",
    "test_collect_single_row_key",
    "test_hydrate_capability_rechecked_before_submit",
    "test_hydrate_chip_does_not_block_revivable_bundle",
    "test_run_bulk_reports_counts_with_reasons",
    "test_run_failed_rows_reported_without_overlay",
    "test_run_restore_and_show_filter_hidden_warns",
    "test_run_restore_and_show_reload_pending_stays_neutral",
    "test_run_restore_and_show_reveals_in_inbox",
    "test_run_single_restore_marks_overlay_and_toasts",
]


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
    owner = make_owner()
    open_archive(owner)
    with override_flags(agents_archive_view=True):
        keys, skipped = collect_archive_restore_keys(owner)
    assert keys == ["u.m@r1"]
    assert skipped == []


def test_collect_banner_and_pulse_skipped() -> None:
    owner = make_owner()
    with override_flags(agents_archive_view=True):
        open_archive(owner, selected_key="banner:day:2026-10-10")
        keys, skipped = collect_archive_restore_keys(owner)
        assert keys == []
        assert len(skipped) == 1
        assert skipped[0].reason == "not an archived run"
        open_archive(owner, selected_key="u.m@r1")
        owner._agents_archive_view.archive.focused_section = ARCHIVE_SECTION_PULSE
        keys, skipped = collect_archive_restore_keys(owner)
        assert keys == []
        assert len(skipped) == 1


def test_collect_marked_wins_over_cursor() -> None:
    owner = make_owner()
    open_archive(owner, selected_key="u.m@cursor")
    owner._agents_archive_view.archive.marks = frozenset({"u.m@a1", "u.m@a2"})
    with override_flags(agents_archive_view=True):
        keys, _skipped = collect_archive_restore_keys(owner)
    assert sorted(keys) == ["u.m@a1", "u.m@a2"]


def test_collect_container_expands_loaded_members() -> None:
    from sase.ace.tui.actions.agents._archive_column import _ColumnRuntime
    from sase.ace.tui.models.agent_archive_list import ITEM_CONTAINER, ITEM_MEMBER

    owner = make_owner()
    open_archive(owner, selected_key="container:archive:u.m@clan1")
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

    owner = make_owner()
    open_archive(owner, selected_key="container:archive:u.m@clan1")
    runtime = _ColumnRuntime()
    runtime.model = SimpleNamespace(items=[])  # type: ignore[assignment]
    owner._archive_column_runtime = runtime
    with override_flags(agents_archive_view=True):
        keys, skipped = collect_archive_restore_keys(owner)
    assert keys == []
    assert len(skipped) == 1
    assert "expand" in skipped[0].reason


def test_hydrate_capability_rechecked_before_submit(monkeypatch: Any) -> None:
    owner = make_owner()
    agent = make_agent(durably_revivable=False)
    wire_bundles(monkeypatch, owner, {"u.m@r1": (make_row(), agent, False)})
    with override_flags(agents_archive_view=True):
        found, _row_out, reason = hydrate_archive_candidate(owner, "u.m@r1")
    # The agent is reported so the chooser can still offer Open chat,
    # Fork, and Copy; the reason keeps it out of the restore submission.
    assert found is agent
    assert reason == "can't restore"


def test_hydrate_chip_does_not_block_revivable_bundle(monkeypatch: Any) -> None:
    owner = make_owner()
    agent = make_agent()
    wire_bundles(
        monkeypatch,
        owner,
        {
            "u.m@chip": (make_row(restorable=False), agent, False),
            "u.m@bad": (make_row(), make_agent(), True),
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
    owner = make_owner()
    open_archive(owner)
    agent = make_agent()
    wire_bundles(monkeypatch, owner, {"u.m@r1": (make_row(), agent, False)})
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
    owner = make_owner()
    open_archive(owner, selected_key="u.m@good")
    good = make_agent("good.run")
    locked = make_agent("locked.run", durably_revivable=False)
    wire_bundles(
        monkeypatch,
        owner,
        {
            "u.m@good": (make_row("good.run"), good, False),
            "u.m@locked": (make_row("locked.run", restorable=False), locked, False),
            "u.m@bad": (make_row("gone.run"), make_agent("gone.run"), True),
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
    owner = make_owner()
    open_archive(owner)
    agent = make_agent()
    wire_bundles(monkeypatch, owner, {"u.m@r1": (make_row(), agent, False)})
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
    owner = make_owner()
    open_archive(owner)
    agent = make_agent()
    wire_bundles(monkeypatch, owner, {"u.m@r1": (make_row(), agent, False)})
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
    owner = make_owner()
    open_archive(owner)
    agent = make_agent()
    wire_bundles(monkeypatch, owner, {"u.m@r1": (make_row(), agent, False)})
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
    owner = make_owner()
    open_archive(owner)
    agent = make_agent()
    wire_bundles(monkeypatch, owner, {"u.m@r1": (make_row(), agent, False)})
    _revive_stub(owner, revived=(agent,))
    owner._select_revived_agent = lambda _agent: False  # type: ignore[attr-defined]
    owner._agents_with_children = []  # type: ignore[attr-defined]
    with override_flags(agents_archive_view=True):
        run_archive_restore(owner, and_show=True)
    assert owner.notices == [
        ("bob-cli-5p.4 is back in the inbox · no new run started", "information")
    ]
