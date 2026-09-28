"""Tests for the glance-row-chips phase (epic sase-1bt, sase-1bt.4)."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.actions.event_refresh._surface_tokens import (
    SurfaceTokenSnapshot,
    probe_tool_runs_token,
    surface_token_drifted,
)
from sase.ace.tui.tool_runs.attribution import _RowIdentity, select_live_runs
from sase.ace.tui.tool_runs.row_chip import (
    _minute_bucket,
    _order_live_runs,
    chip_uses_elapsed_fallback,
    row_chip_for_runs,
    tool_run_chip_token,
)
from sase.ace.tui.tool_runs import snapshot as _snapshot_module
from sase.ace.tui.tool_runs.snapshot import (
    _build_snapshot,
    _set_snapshot,
    apply_loaded_snapshot,
    get_snapshot,
)
from sase.core.tool_run import ToolRunGlance


def _glance(
    run_id: str,
    *,
    agent: str | None = None,
    owner_kind: str | None = None,
    owner_id: str | None = None,
    state: str = "running",
    label: str = "check",
    created_ts: int = 1000,
    last_activity_ts: int = 1000,
    stages_done: int = 6,
    stages_expected: int | None = 11,
    parent_run_id: str | None = None,
    stop_requested: bool = False,
) -> ToolRunGlance:
    return ToolRunGlance(
        run_id=run_id,
        label=label,
        state=state,
        created_ts=created_ts,
        last_activity_ts=last_activity_ts,
        stages_done=stages_done,
        stop_requested=stop_requested,
        tool_name="check",
        agent=agent,
        owner_kind=owner_kind,
        owner_id=owner_id,
        parent_run_id=parent_run_id,
        running_ts=created_ts,
        current_stage=None,
        stages_expected=stages_expected,
        typical_ms=None,
    )


def _clear_snapshot_state() -> None:
    _set_snapshot(None)
    _snapshot_module._TOOL_RUNS_DISABLED_REASON = None
    _snapshot_module._TOOL_RUNS_DISABLED_LOGGED = False


def setup_function(_: object) -> None:
    _clear_snapshot_state()


def teardown_function(_: object) -> None:
    _clear_snapshot_state()


def test_owner_first_monitor_row() -> None:
    owned = _glance("a", agent="0t9--code", owner_kind="monitor", owner_id="m1")
    unowned = _glance("b", agent="0t9--code")
    row = _RowIdentity(agent_name="0t9--code", monitor_id="m1", is_monitor_row=True)
    assert select_live_runs([owned, unowned], row) == (owned,)


def test_agent_turn_excludes_owned_runs() -> None:
    owned = _glance("a", agent="0t9--code", owner_kind="monitor", owner_id="m1")
    unowned = _glance("b", agent="0t9--code")
    row = _RowIdentity(agent_name="0t9--code")
    assert select_live_runs([owned, unowned], row) == (unowned,)


def test_session_container_unions_members_and_own_name() -> None:
    r1 = _glance("a", agent="member-1")
    r2 = _glance("b", agent="sess")
    r3 = _glance("c", agent="other")
    row = _RowIdentity(
        agent_name="sess",
        is_session_container=True,
        session_member_names=("member-1", "member-2"),
        container_name="sess",
    )
    assert select_live_runs([r1, r2, r3], row) == (r1, r2)


def test_remote_and_clan_rows_never_match() -> None:
    run = _glance("a", agent="x")
    assert select_live_runs([run], _RowIdentity(agent_name="x", is_remote=True)) == ()
    assert select_live_runs([run], _RowIdentity(agent_name="x", is_clan=True)) == ()


def test_parent_folds_child_without_plus_n() -> None:
    parent = _glance("p", agent="x", created_ts=1000)
    child = _glance("c", agent="x", created_ts=1010, parent_run_id="p")
    row = _RowIdentity(agent_name="x")
    selected = select_live_runs([parent, child], row)
    assert selected == (parent,)
    chip = row_chip_for_runs(selected, 1100.0, 60)
    assert chip is not None
    assert "+1" not in chip[0]


def test_second_live_run_appends_plus_n() -> None:
    r1 = _glance("a", agent="x", created_ts=1000)
    r2 = _glance("b", agent="x", created_ts=1010)
    row = _RowIdentity(agent_name="x")
    selected = select_live_runs([r1, r2], row)
    assert len(selected) == 2
    chip = row_chip_for_runs(selected, 1100.0, 60)
    assert chip is not None
    assert chip[0].endswith("+1")


def test_progress_chip_and_silent_chip() -> None:
    live = _glance("a", agent="x", created_ts=1000, last_activity_ts=1090)
    chip = row_chip_for_runs([live], 1100.0, 60)
    assert chip is not None
    assert chip[0] == "⚒ check 7/11"
    assert chip[1] == "bold #87D7FF"
    silent = _glance("b", agent="x", created_ts=1000, last_activity_ts=500)
    chip = row_chip_for_runs([silent], 1100.0, 60)
    assert chip is not None
    assert "silent" in chip[0]
    assert chip[0].startswith("⚒⚠")
    assert chip[1] == "bold #FF5F5F"


def test_silent_outranks_live_in_ordering() -> None:
    live = _glance("a", agent="x", created_ts=900, last_activity_ts=1095)
    silent = _glance("b", agent="x", created_ts=1000, last_activity_ts=500)
    ordered = _order_live_runs([live, silent], 1100.0, 60)
    assert ordered[0].run_id == "b"


def test_minute_bucket_in_token() -> None:
    run = _glance("a", agent="x", created_ts=1000, last_activity_ts=1090)
    t1 = tool_run_chip_token([run], 1100.0, 60)
    t2 = tool_run_chip_token([run], 1101.0, 60)
    t3 = tool_run_chip_token([run], 1160.0, 60)
    assert t1 == t2
    assert t1 != t3
    assert tool_run_chip_token([], 1100.0, 60) is None


def test_progress_chip_does_not_use_elapsed_but_fallback_does() -> None:
    progress = _glance("a", agent="x", stages_expected=11, last_activity_ts=1095)
    assert chip_uses_elapsed_fallback([progress], 1100.0, 60) is False
    fallback = _glance("b", agent="x", stages_expected=None, last_activity_ts=1095)
    assert chip_uses_elapsed_fallback([fallback], 1100.0, 60) is True
    assert _minute_bucket(119.0) == 1


def test_snapshot_publish_and_apply() -> None:
    assert get_snapshot() is None
    snap = _build_snapshot([_glance("a", agent="x")], generation=1)
    _set_snapshot(snap)
    assert get_snapshot() is snap
    assert get_snapshot() is not None and get_snapshot().has_live_runs  # type: ignore[union-attr]
    assert apply_loaded_snapshot(None) is snap


def test_probe_tool_runs_token_stats_both_files(tmp_path: Path) -> None:
    store = tmp_path / "runs.sqlite"
    wal = tmp_path / "runs.sqlite-wal"
    store.write_bytes(b"abc")
    first = probe_tool_runs_token(store, wal)
    assert first.surface == "tool_runs"
    assert not first.indeterminate
    assert not surface_token_drifted(first, first)
    store.write_bytes(b"abcd")
    second = probe_tool_runs_token(store, wal)
    assert surface_token_drifted(second, first)
    # None last is always dirty (fail open).
    assert surface_token_drifted(first, None)


def test_snapshot_surface_token_has_tool_runs() -> None:
    from sase.ace.tui.actions.event_refresh._surface_tokens import SurfaceToken

    def _tok(surface: str) -> SurfaceToken:
        return SurfaceToken(surface=surface, parts=((f"/{surface}", True, 1, 1),))

    snap = SurfaceTokenSnapshot(
        agents=_tok("agents"),
        axe=_tok("axe"),
        notifications=_tok("notifications"),
        patches=_tok("patches"),
        procs=_tok("procs"),
    )
    assert snap.tool_runs is None
    assert snap.token_for("agents").surface == "agents"
    full = SurfaceTokenSnapshot(
        agents=_tok("agents"),
        axe=_tok("axe"),
        notifications=_tok("notifications"),
        patches=_tok("patches"),
        procs=_tok("procs"),
        tool_runs=_tok("tool_runs"),
    )
    assert full.token_for("tool_runs").surface == "tool_runs"


def test_row_status_appends_chip_behind_flag() -> None:
    from rich.text import Text

    from sase.ace.tui.models.agent import Agent, AgentType
    from sase.ace.tui.widgets._agent_list_render_agent_status import (
        append_agent_row_status,
    )

    from datetime import datetime

    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="agent",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 31, 12, 0, 0),
        raw_suffix="20260531120000",
    )
    agent.agent_name = "chip-agent"
    run = _glance(
        "deadbeef", agent="chip-agent", created_ts=1000, last_activity_ts=1090
    )
    _set_snapshot(_build_snapshot([run], generation=1))
    text = Text("row ")
    append_agent_row_status(text, agent, now=None)
    assert "⚒" in text.plain
