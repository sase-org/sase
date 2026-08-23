"""Procs query row adapter and the ``ProcQueryFilter`` facade."""

from __future__ import annotations

from datetime import datetime, timedelta
import time

import pytest

from sase.ace.query.profile_reference import ProfileQueryError
from sase.ace.tui._proc_observer_models import ObservedProc
from sase.ace.tui._proc_query import (
    PROC_QUERY_OUTPUT_TAIL_CHARS,
    ProcQueryFilter,
    proc_query_row,
    query_needs_output,
)
from sase.monitor_state import MONITOR_PROC_ORIGIN

_NOW = datetime(2026, 8, 20, 12, 0, 0)


def _proc(
    proc_id: str,
    *,
    status: str = "success",
    started_at: datetime = _NOW,
    finished_at: datetime | None = None,
    command: list[str] | None = None,
    display_name: str | None = None,
    output: str = "",
    origin: str = "",
    shell_name: str | None = None,
    session_id: str | None = None,
    session_live: bool = True,
    exit_code: int | None = None,
    project: str | None = None,
) -> ObservedProc:
    return ObservedProc(
        proc_id=proc_id,
        proc_type="command",
        cl_name="",
        project_file="",
        status=status,
        message="",
        started_at=started_at,
        display_name=display_name,
        finished_at=finished_at,
        output=output,
        command=command,
        origin=origin,
        shell_name=shell_name,
        session_id=session_id,
        session_live=session_live,
        exit_code=exit_code,
        project=project,
    )


def _ids(matched: list[ObservedProc]) -> list[str]:
    return [proc.proc_id for proc in matched]


# --- Empty query is a no-op ---------------------------------------------------


def test_empty_query_returns_all_rows_unfiltered() -> None:
    procs = [_proc("a"), _proc("b")]
    filt = ProcQueryFilter()
    assert filt.matching("", procs, now=_NOW) == procs
    assert filt.matching("   ", procs, now=_NOW) == procs


# --- Boolean fields: bare and negated spellings -------------------------------


def test_monitor_bare_and_negated_spellings_select_by_origin() -> None:
    procs = [
        _proc("mon", origin=MONITOR_PROC_ORIGIN, shell_name="acme--mon"),
        _proc("plain"),
    ]
    filt = ProcQueryFilter()
    assert _ids(filt.matching("monitor", procs, now=_NOW)) == ["mon"]
    assert _ids(filt.matching("-monitor", procs, now=_NOW)) == ["plain"]
    assert _ids(filt.matching("monitor:true", procs, now=_NOW)) == ["mon"]
    assert _ids(filt.matching("monitor:false", procs, now=_NOW)) == ["plain"]


def test_running_is_active_status_owned_by_a_live_session() -> None:
    procs = [
        _proc("live", status="running", session_id="s1", session_live=True),
        _proc("stale", status="running", session_id="s1", session_live=False),
        _proc("done", status="success", finished_at=_NOW),
    ]
    filt = ProcQueryFilter()
    assert _ids(filt.matching("running", procs, now=_NOW)) == ["live"]
    assert _ids(filt.matching("-running", procs, now=_NOW)) == ["stale", "done"]


def test_failed_is_error_or_killed() -> None:
    procs = [
        _proc("err", status="error", finished_at=_NOW),
        _proc("killed", status="killed", finished_at=_NOW),
        _proc("ok", status="success", finished_at=_NOW),
    ]
    filt = ProcQueryFilter()
    assert _ids(filt.matching("failed", procs, now=_NOW)) == ["err", "killed"]


# --- min/max: runtime for finished and still-running procs -------------------


def test_min_and_max_read_runtime_for_finished_and_running_procs() -> None:
    procs = [
        _proc(
            "short",
            started_at=_NOW - timedelta(seconds=100),
            finished_at=_NOW,
        ),
        _proc(
            "long",
            started_at=_NOW - timedelta(seconds=400),
            finished_at=_NOW,
        ),
        _proc(
            "still-running",
            status="running",
            started_at=_NOW - timedelta(seconds=500),
        ),
    ]
    filt = ProcQueryFilter()
    assert _ids(filt.matching("min:300", procs, now=_NOW)) == ["long", "still-running"]
    assert _ids(filt.matching("max:300", procs, now=_NOW)) == ["short"]
    assert _ids(filt.matching("min:5m", procs, now=_NOW)) == ["long", "still-running"]


# --- before/after (completion) vs since/until (start) ------------------------


def test_before_after_bound_completion_time_and_exclude_running_procs() -> None:
    procs = [
        _proc("early", finished_at=datetime(2026, 8, 18, 12, 0, 0)),
        _proc("late", finished_at=datetime(2026, 8, 22, 12, 0, 0)),
        _proc("running", status="running", started_at=_NOW),
    ]
    filt = ProcQueryFilter()
    assert _ids(filt.matching("before:2026-08-20T12:00", procs, now=_NOW)) == ["early"]
    assert _ids(filt.matching("after:2026-08-20T12:00", procs, now=_NOW)) == ["late"]
    # NOT over a missing completion time includes the still-running proc.
    assert _ids(filt.matching("-before:2026-08-20T12:00", procs, now=_NOW)) == [
        "late",
        "running",
    ]


def test_since_until_bound_start_time_and_include_running_procs() -> None:
    procs = [
        _proc(
            "early-start",
            started_at=datetime(2026, 8, 18, 12, 0, 0),
            finished_at=_NOW,
        ),
        _proc(
            "late-start",
            started_at=datetime(2026, 8, 22, 12, 0, 0),
            finished_at=_NOW,
        ),
        _proc(
            "running-late-start",
            status="running",
            started_at=datetime(2026, 8, 22, 12, 0, 0),
        ),
    ]
    filt = ProcQueryFilter()
    assert _ids(filt.matching("since:2026-08-20T12:00", procs, now=_NOW)) == [
        "late-start",
        "running-late-start",
    ]
    assert _ids(filt.matching("until:2026-08-20T12:00", procs, now=_NOW)) == [
        "early-start"
    ]


# --- Free text, text:, cmd:, out: ---------------------------------------------


def test_free_text_matches_command_label_and_output() -> None:
    procs = [
        _proc("by-cmd", command=["just", "check"]),
        _proc("by-name", display_name="check the deploy"),
        _proc("by-out", output="ran just check\n"),
        _proc("none", command=["ls"], display_name="unrelated", output="quiet"),
    ]
    filt = ProcQueryFilter()
    expected = {"by-cmd", "by-name", "by-out"}
    assert set(_ids(filt.matching("check", procs, now=_NOW))) == expected
    assert set(_ids(filt.matching("text:check", procs, now=_NOW))) == expected


def test_cmd_and_out_scope_to_one_side_of_the_corpus() -> None:
    procs = [
        _proc("by-cmd", command=["just", "check"], output="quiet"),
        _proc("by-out", command=["ls"], output="ran just check"),
    ]
    filt = ProcQueryFilter()
    assert _ids(filt.matching("cmd:check", procs, now=_NOW)) == ["by-cmd"]
    assert _ids(filt.matching("out:check", procs, now=_NOW)) == ["by-out"]


def test_output_tail_is_capped_at_32kb() -> None:
    big_output = "x" * (PROC_QUERY_OUTPUT_TAIL_CHARS + 10) + "needle"
    proc = _proc("big", output=big_output)
    filt = ProcQueryFilter()
    assert _ids(filt.matching("out:needle", [proc], now=_NOW)) == ["big"]
    row = proc_query_row(proc, now=_NOW, with_output=True)
    assert len(row["fields"]["out"]) == PROC_QUERY_OUTPUT_TAIL_CHARS


# --- agent:, project:, exit:, name: --------------------------------------------


def test_agent_field_matches_only_a_monitor_rows_member_agent_name() -> None:
    procs = [
        _proc("mon", origin=MONITOR_PROC_ORIGIN, shell_name="acme--mon"),
        _proc("plain", shell_name="acme--mon"),
    ]
    filt = ProcQueryFilter()
    assert _ids(filt.matching("agent:acme", procs, now=_NOW)) == ["mon"]


def test_project_field_matches_the_project_key() -> None:
    procs = [_proc("in-project", project="sase"), _proc("no-project")]
    filt = ProcQueryFilter()
    assert _ids(filt.matching("project:sase", procs, now=_NOW)) == ["in-project"]


def test_exit_field_matches_the_exact_exit_code() -> None:
    procs = [
        _proc("zero", finished_at=_NOW, exit_code=0),
        _proc("one", status="error", finished_at=_NOW, exit_code=1),
    ]
    filt = ProcQueryFilter()
    assert _ids(filt.matching("exit:1", procs, now=_NOW)) == ["one"]


def test_name_field_matches_the_row_label() -> None:
    procs = [
        _proc("named", display_name="deploy prod"),
        _proc("other", display_name="build"),
    ]
    filt = ProcQueryFilter()
    assert _ids(filt.matching("name:deploy", procs, now=_NOW)) == ["named"]


# --- The epic's worked example ------------------------------------------------


def test_worked_example_just_check_excludes_monitor_and_long_procs() -> None:
    procs = [
        _proc(
            "matches",
            command=["just", "check"],
            started_at=_NOW - timedelta(seconds=100),
            finished_at=_NOW,
        ),
        _proc(
            "monitor-row",
            command=["just", "check"],
            origin=MONITOR_PROC_ORIGIN,
            shell_name="acme--mon",
            started_at=_NOW - timedelta(seconds=100),
            finished_at=_NOW,
        ),
        _proc(
            "too-long",
            command=["just", "check"],
            started_at=_NOW - timedelta(seconds=400),
            finished_at=_NOW,
        ),
        _proc("unrelated", command=["ls"], finished_at=_NOW),
    ]
    filt = ProcQueryFilter()
    assert _ids(filt.matching('"just check" -monitor -min:300', procs, now=_NOW)) == [
        "matches"
    ]


# --- query_needs_output --------------------------------------------------------


def test_query_needs_output_gates_on_free_text_and_text_out_keys() -> None:
    filt = ProcQueryFilter()
    assert query_needs_output(filt.parse("monitor -min:300")) is False
    assert query_needs_output(filt.parse('"just check"')) is True
    assert query_needs_output(filt.parse("text:foo")) is True
    assert query_needs_output(filt.parse("out:foo")) is True
    assert query_needs_output(filt.parse("cmd:foo name:bar")) is False


# --- Parse errors surface as the shared ProfileQueryError --------------------


def test_invalid_query_raises_profile_query_error() -> None:
    filt = ProcQueryFilter()
    with pytest.raises(ProfileQueryError):
        filt.matching("status:not-a-real-status", [], now=_NOW)


# --- Evaluation budget ---------------------------------------------------------


def test_whole_corpus_evaluation_stays_within_budget() -> None:
    procs = [
        _proc(
            f"proc-{i}",
            command=["just", "check", str(i)],
            output=f"line {i}\n" * 200,
            status="running" if i % 5 == 0 else "success",
            started_at=_NOW - timedelta(seconds=i),
            finished_at=None if i % 5 == 0 else _NOW,
        )
        for i in range(500)
    ]
    filt = ProcQueryFilter()
    start = time.perf_counter()
    filt.matching('"just check" -monitor -min:10', procs, now=_NOW)
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0
