"""Archive proof: cross-phase regression coverage for child epic ``sase-1jm.3.1``.

Each test drives two or more Archive phases through one owner so the seams
meet the way the TUI uses them: flag-gated entry (view-foundation),
generation-safe loading (corpus-controller), the typed selection
(archive-column), parked query routing (query-parking), read-only hydration
(archive-reader), and live-action guards (action-boundary). Unit coverage for
each phase lives in its own module; nothing here re-proves a single seam.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sase.ace.query.scope_token import ScopeTokenError, extract_scope
from sase.ace.tui.actions.agents._archive_actions import (
    archive_marked_run_keys,
    archive_read_target,
    guard_archive_live_action,
    resolve_agents_read_agent,
    toggle_archive_mark,
)
from sase.ace.tui.actions.agents._archive_controller import (
    archive_corpus_snapshot,
    cancel_archive_controller,
    note_inbox_applied_for_archive,
    request_archive_view_load,
)
from sase.ace.tui.actions.agents._archive_reader import hydrated_archive_agent_for
from sase.ace.tui.actions.agents._archive_view import (
    archive_detail_owns_panel,
    archive_read_only_context,
    close_agents_archive_view,
    get_agents_tab_selection,
    init_agents_archive_view_state,
    open_agents_archive_view,
    open_agents_archive_view_with_query,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_archive_controller import preserve_archive_selected_key
from sase.ace.tui.models.agent_archive_list import archive_row_key
from sase.ace.tui.models.agent_archive_reader import mark_agent_archive_read_only
from sase.ace.tui.models.agent_archive_view import (
    AGENTS_VIEW_ARCHIVE,
    AGENTS_VIEW_INBOX,
    ARCHIVE_ROW_AGENT,
    ARCHIVE_ROW_NONE,
    ARCHIVE_STATUS_ALREADY_INBOX,
    ARCHIVE_STATUS_DISABLED,
    ARCHIVE_STATUS_OPENED,
    ARCHIVE_STATUS_RETURNED,
    agent_is_archive_read_only,
)
from sase.core.agent_archive_facade import compile_agent_archive_corpus
from sase.feature_flags import override_flags
from tests._agent_archive_index_fixtures import insert_archive_rows
from tests.ace.tui._agent_archive_column_helpers import (
    ColumnHarness,
    ModelCorpus,
    complete_load,
    light_row,
)


def _live_agent(name: str = "live-agent") -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/proof.sase",
        status="RUNNING",
        start_time=None,
        workflow="crs",
        raw_suffix="20261010120000",
        agent_name="live.agent",
    )


def _proof_owner() -> SimpleNamespace:
    """An owner with a live Inbox selection, marks, and unread state."""
    owner = SimpleNamespace()
    owner._inbox_agent = _live_agent()
    owner._get_selected_agent = lambda: owner._inbox_agent
    owner._marked_agents = {"live:mark:1"}
    owner._unread_completed_agent_ids = {"live:unread:1"}
    owner._pending_attention_count = 2
    owner._agent_search_query = "model:opus"
    owner.current_idx = 3
    owner.current_tab = "agents"
    owner.notices: list[tuple[str, str]] = []

    def notify(message: str, severity: str = "information") -> None:
        owner.notices.append((message, severity))

    owner.notify = notify
    init_agents_archive_view_state(owner)
    return owner


def _proof_history() -> list[dict[str, Any]]:
    rows = [
        light_row(f"p{i:02d}", day="2026-10-10", hour=20 - i, name=f"today.{i:02d}")
        for i in range(5)
    ]
    rows += [
        light_row(f"q{i:02d}", day="2026-10-09", hour=18 - i, name=f"yday.{i:02d}")
        for i in range(3)
    ]
    return rows


# -- flag states -------------------------------------------------------------


def test_beta_off_open_is_disabled_and_inbox_untouched() -> None:
    owner = _proof_owner()
    with override_flags():
        assert open_agents_archive_view(owner).status == ARCHIVE_STATUS_DISABLED
        assert close_agents_archive_view(owner).status == ARCHIVE_STATUS_ALREADY_INBOX
        selection = get_agents_tab_selection(owner)
        assert selection.view == AGENTS_VIEW_INBOX
        assert selection.row_kind == ARCHIVE_ROW_AGENT
        assert selection.agent is owner._inbox_agent
        assert not archive_detail_owns_panel(owner)
        assert archive_read_only_context(owner) is None
        assert owner._agent_search_query == "model:opus"
        assert owner.current_idx == 3


def test_beta_off_never_compiles_the_corpus() -> None:
    harness = ColumnHarness(_proof_history())
    with override_flags():
        request_archive_view_load(harness.owner)
        harness.note_inbox_applied()
        assert harness.corpus.summary_calls == 0
        cancel_archive_controller(harness.owner)


def test_beta_on_full_open_read_return_round_trip() -> None:
    harness = ColumnHarness(_proof_history())
    owner = harness.owner
    owner._inbox_agent = _live_agent()
    owner._get_selected_agent = lambda: owner._inbox_agent
    owner._agent_search_query = "model:opus"
    with override_flags(agents_archive_view=True):
        opened = open_agents_archive_view(owner)
        assert opened.status == ARCHIVE_STATUS_OPENED
        assert opened.committed_query == "in:archive"
        assert owner._agents_archive_view.active_view == AGENTS_VIEW_ARCHIVE
        # The Inbox is parked, never replaced.
        parked = owner._agents_archive_view.parked_inbox
        assert parked is not None
        assert parked.committed_query == "model:opus"

        selection = get_agents_tab_selection(owner)
        assert selection.view == AGENTS_VIEW_ARCHIVE
        assert selection.read_only is True
        # No rows are loaded yet, so the empty selection is not an agent —
        # but it is still Archive-owned and read-only.
        assert selection.row_kind == ARCHIVE_ROW_NONE
        assert selection.agent is None
        assert archive_detail_owns_panel(owner)

        returned = close_agents_archive_view(owner)
        assert returned.status == ARCHIVE_STATUS_RETURNED
        assert owner._agents_archive_view.active_view == AGENTS_VIEW_INBOX
        assert owner._agent_search_query == "model:opus"
        assert not archive_detail_owns_panel(owner)
        back = get_agents_tab_selection(owner)
        assert back.view == AGENTS_VIEW_INBOX
        assert back.agent is owner._inbox_agent


def test_explicit_arrival_carries_a_scoped_query() -> None:
    owner = _proof_owner()
    with override_flags(agents_archive_view=True):
        outcome = open_agents_archive_view_with_query(
            owner, query="in:archive outcome:failed", agent_name=None
        )
        assert outcome.status == ARCHIVE_STATUS_OPENED
        assert outcome.committed_query == "in:archive outcome:failed"
        assert owner._agents_archive_view.active_view == AGENTS_VIEW_ARCHIVE
        assert (
            owner._agents_archive_view.parked_inbox is not None
            and owner._agents_archive_view.parked_inbox.committed_query == "model:opus"
        )


# -- query routing and scope errors ------------------------------------------


def test_scope_errors_never_change_the_active_view() -> None:
    owner = _proof_owner()
    with override_flags(agents_archive_view=True):
        open_agents_archive_view(owner)
        # An unknown scope token is a validation error, not a view change.
        with_diff_scope = "in:everywhere"
        try:
            extract_scope(with_diff_scope)
            scope_error: str | None = None
        except ScopeTokenError as exc:
            scope_error = str(exc)
        assert scope_error, "unknown scope must raise a hint, not switch views"
        assert owner._agents_archive_view.active_view == AGENTS_VIEW_ARCHIVE

        # Uncommitted editing text never changes the view either: only the
        # committed query owns the view, and it still holds in:archive.
        assert owner._agents_archive_view.archive.committed_query == "in:archive"
        close_agents_archive_view(owner)
        assert owner._agents_archive_view.active_view == AGENTS_VIEW_INBOX


def test_inbox_scope_routes_to_the_inbox() -> None:
    remainder, scope = extract_scope("in:inbox model:opus")
    assert scope == "inbox"
    assert "model:opus" in remainder
    remainder, scope = extract_scope("in:archive outcome:failed")
    assert scope == "archive"


# -- loading gate and identity stability -------------------------------------


async def test_no_corpus_compile_before_the_first_complete_inbox_load() -> None:
    harness = ColumnHarness(_proof_history())
    owner = harness.owner
    with override_flags(agents_archive_view=True):
        # An early explicit open paints loading chrome and queues work, but
        # nothing compiles before the Inbox gate settles.
        open_agents_archive_view(owner)
        request_archive_view_load(owner)
        await harness.settle()
        assert harness.corpus.summary_calls == 0

        note_inbox_applied_for_archive(owner, load_state=complete_load())
        await harness.settle()
        assert harness.corpus.summary_calls >= 1


def test_incomplete_inbox_load_keeps_the_gate_shut() -> None:
    harness = ColumnHarness(_proof_history())
    owner = harness.owner
    with override_flags(agents_archive_view=True):
        open_agents_archive_view(owner)
        note_inbox_applied_for_archive(
            owner,
            load_state=SimpleNamespace(
                complete_history=False,
                artifact_source="full",
                bounded_prefix=True,
                complete_visible_inbox=False,
                truncated=False,
                query_incomplete=True,
            ),
        )
        assert harness.corpus.summary_calls == 0
        cancel_archive_controller(owner)


def test_selection_identity_survives_a_corpus_rebuild() -> None:
    before = ("u.m@r1", "u.m@r2", "u.m@r3")
    assert preserve_archive_selected_key(before, "u.m@r2", before) == "u.m@r2"
    # A vanished identity falls to the nearest still-valid neighbor.
    assert preserve_archive_selected_key(before, "u.m@r2", ("u.m@r1", "u.m@r3")) in {
        "u.m@r1",
        "u.m@r3",
    }
    assert preserve_archive_selected_key(before, "u.m@r2", ()) is None
    assert preserve_archive_selected_key(before, None, ("u.m@r9",)) == "u.m@r9"


async def test_footer_syncs_on_snapshot_without_cursor_moves() -> None:
    """The Archive footer follows ownership, not incidental render paths.

    Opening the Archive must install the conditional footer even when no
    cursor move ever schedules a detail render (empty states, unreadable
    cards, and plain opens all apply a snapshot with zero navigation).
    """
    harness = ColumnHarness(_proof_history())
    calls: list[int] = []
    harness.owner._refresh_agent_footer_bindings_only = lambda: calls.append(1)
    with override_flags(agents_archive_view=True):
        harness.note_inbox_applied()
        open_agents_archive_view(harness.owner)
        await harness.settle()
        assert calls, (
            "applying the warm snapshot must sync the Archive footer "
            "without any cursor move"
        )


async def test_loaded_selection_reveals_and_stays_stable_across_windows() -> None:
    harness = ColumnHarness(_proof_history())
    with override_flags(agents_archive_view=True):
        harness.note_inbox_applied()
        open_agents_archive_view(harness.owner)
        await harness.settle()
        keys = [item.key for item in harness.widget.last_items if item.row]
        assert keys, "the warm corpus must yield list rows"
        first = keys[0]
        harness.archive.selected_key = first
        snapshot = archive_corpus_snapshot(harness.owner)
        assert snapshot.summary is not None and snapshot.summary["total"] == 8
        selection = get_agents_tab_selection(harness.owner)
        assert selection.view == AGENTS_VIEW_ARCHIVE
        assert selection.row_kind == ARCHIVE_ROW_AGENT
        assert selection.archive_key == first
        assert selection.read_only is True
        assert selection.provenance == "archive"


# -- no-write reading --------------------------------------------------------


def test_read_only_marking_never_rewrites_bundle_state() -> None:
    agent = _live_agent()
    assert agent_is_archive_read_only(agent) is False
    before = dict(agent.__dict__)
    marked = mark_agent_archive_read_only(agent)
    assert agent_is_archive_read_only(marked)
    assert marked.status == "RUNNING", "stored status stays live; guards read the flag"
    after = dict(agent.__dict__)
    assert after.pop("_archive_read_only", None) is True
    assert before.pop("_archive_read_only", None) is False
    assert after == before


def test_marked_running_agent_cannot_start_live_reply_following() -> None:
    from sase.ace.tui.widgets.prompt_panel._live_reply_follow import (
        is_live_reply_agent,
    )

    agent = mark_agent_archive_read_only(_live_agent())
    assert not is_live_reply_agent(agent)
    assert agent_is_archive_read_only(agent)


async def test_pulse_selection_is_not_an_agent() -> None:
    harness = ColumnHarness(_proof_history())
    with override_flags(agents_archive_view=True):
        harness.note_inbox_applied()
        open_agents_archive_view(harness.owner)
        await harness.settle()
        harness.owner._agents_archive_view.archive.focused_section = "pulse"
        selection = get_agents_tab_selection(harness.owner)
        assert selection.row_kind == ARCHIVE_ROW_NONE
        assert selection.agent is None
        assert archive_read_only_context(harness.owner) is None


def test_hydration_cache_miss_resolves_to_no_agent() -> None:
    owner = _proof_owner()
    with override_flags(agents_archive_view=True):
        assert hydrated_archive_agent_for(owner, "u.m@missing") is None
        assert archive_read_target(owner) is None
        assert resolve_agents_read_agent(owner) is owner._inbox_agent


# -- action isolation --------------------------------------------------------


def test_live_guards_block_and_archive_marks_stay_apart() -> None:
    owner = _proof_owner()
    with override_flags(agents_archive_view=True):
        open_agents_archive_view(owner)
        owner._agents_archive_view.archive.selected_key = "u.m@r1"

        assert guard_archive_live_action(owner, "kill_agent") is True
        assert len(owner.notices) == 1
        assert ",a" in owner.notices[0][0]

        assert toggle_archive_mark(owner) is True
        assert archive_marked_run_keys(owner) == frozenset({"u.m@r1"})
        # Inbox marks, unread, and attention are parked and untouched.
        assert owner._marked_agents == {"live:mark:1"}
        assert owner._unread_completed_agent_ids == {"live:unread:1"}
        assert owner._pending_attention_count == 2
        assert owner._get_selected_agent() is owner._inbox_agent


# -- query parity: TUI list order matches the CLI order ----------------------


def _cli_identities(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> list[tuple[str, str, str]]:
    import argparse as _argparse

    from sase.ace import dismissed_agents
    from sase.ace.dismissed_bundle_index import DismissedBundleIndexProgress
    from sase.ace.query_profile import compile_query_profile
    from sase.ace.query_profile.profiles._agents_archive import (
        agents_archive_query_schema,
    )
    from sase.agents import cli_search
    from sase.agents.cli_search import handle_agents_search
    from sase.core import agent_archive_corpus_cache as cache_mod
    from sase.core.agent_archive_corpus_cache import get_agent_archive_corpus
    from sase.project_display_names import (
        ProjectDisplaySnapshot,
        ProjectRefDisplaySnapshot,
    )

    monkeypatch.setattr(dismissed_agents, "_DISMISSED_BUNDLES_DIR", tmp_path)
    monkeypatch.setattr(cache_mod, "_build_fallback_facets", lambda: {})
    display = ProjectRefDisplaySnapshot(
        display_snapshot=ProjectDisplaySnapshot({"sase": "sase"})
    )
    monkeypatch.setattr(
        cli_search, "load_project_ref_display_snapshot", lambda: display
    )
    cache_mod._CACHED = None
    cache_mod._GENERATION = 0
    try:
        get_agent_archive_corpus(
            root=tmp_path,
            progress=DismissedBundleIndexProgress(rebuilding=False, indexed_rows=4),
            link_facets={},
            profile=compile_query_profile(agents_archive_query_schema()),
        )
        code = handle_agents_search(
            _argparse.Namespace(json=True, limit=0, project=None, query=["in:archive"])
        )
        assert code == 0
        actual = json.loads(capsys.readouterr().out)
        return [
            (
                row["archive_key"]["source_username"],
                row["archive_key"]["source_machine"],
                row["archive_key"]["source_run_id"],
            )
            for row in actual
        ]
    finally:
        cache_mod._CACHED = None
        cache_mod._GENERATION = 0


def _parity_rows() -> list[dict[str, Any]]:
    return [
        {
            "run_id": "alpha",
            "name": "261010.alpha",
            "stop_time": "2026-10-10T15:05:00Z",
            "status": "DONE",
        },
        {
            "run_id": "beta",
            "name": "261010.beta",
            "stop_time": "2026-10-10T14:05:00Z",
            "status": "FAILED",
        },
        {
            "run_id": "gamma",
            "name": "261009.gamma",
            "stop_time": "2026-10-09T12:00:00Z",
            "status": "DONE",
        },
    ]


async def test_tui_list_order_matches_cli_identity_order(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    insert_archive_rows(tmp_path, _parity_rows())
    corpus = compile_agent_archive_corpus(
        root=tmp_path,
        index_status={"status": "ok"},
        timezone="UTC",
        link_facets={},
    )
    cli_order = _cli_identities(tmp_path, monkeypatch, capsys)
    assert [run for _, _, run in cli_order] == ["alpha", "beta", "gamma"]

    with override_flags(agents_archive_view=True):
        harness = ColumnHarness([], corpus=corpus)
        harness.note_inbox_applied()
        open_agents_archive_view(harness.owner)
        await harness.settle()
        listed = [
            archive_row_key(item.row) for item in harness.widget.last_items if item.row
        ]
        expected = [f"{user}.{machine}@{run}" for user, machine, run in cli_order]
        assert listed == expected, (
            "the TUI list must present the same identities in the same order "
            "as `sase agent search in:archive`"
        )


def test_light_row_keys_are_stable_archive_identities() -> None:
    row = light_row("r7", name="stable.name")
    assert archive_row_key(row) == "u.m@r7"
    assert archive_row_key({}) is None
