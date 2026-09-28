"""Tests for scheduler in-flight launch detection."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.state import (
    ChopRunEntry,
    atomic_write_json,
    chop_run_result_path,
    ensure_chop_dirs,
    jack_state_dir,
    write_chop_run,
    write_lumberjack_pid,
)


@pytest.fixture
def temp_state_dir(tmp_path: Path) -> Iterator[Path]:
    state_dir = tmp_path / ".sase" / "axe"
    lumberjack_dir = state_dir / "lumberjacks"
    shared_dir = state_dir / "shared"
    with (
        patch("sase.axe.state.axe_state_dir", return_value=state_dir),
        patch("sase.axe.state.jack_state_dir", return_value=lumberjack_dir),
        patch("sase.axe.state.shared_state_dir", return_value=shared_dir),
    ):
        yield state_dir


def _write_run(
    lumberjack: str,
    chop: str,
    run_id: str,
    *,
    status: str = "running",
    finished_at: str | None = None,
) -> None:
    entry = ChopRunEntry(
        run_id=run_id,
        lumberjack_name=lumberjack,
        chop_name=chop,
        started_at="2026-09-28T09:32:00-04:00",
        finished_at=finished_at,
        duration_ms=0,
        status=status,  # type: ignore[arg-type]
    )
    write_chop_run(entry)


def _write_result(
    lumberjack: str, chop: str, run_id: str, proposed: list[dict]
) -> None:
    ensure_chop_dirs(lumberjack, chop)
    atomic_write_json(
        chop_run_result_path(lumberjack, chop, run_id),
        {"proposed_launches": proposed},
    )


def _write_records(lumberjack: str, chop: str, run_id: str, count: int) -> None:
    path = jack_state_dir() / lumberjack / "agent_chops.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    records = []
    for i in range(count):
        records.append(
            {
                "lumberjack_name": lumberjack,
                "chop_name": chop,
                "prompt_hash": "abc",
                "pid": 1000 + i,
                "project_file": "/tmp/project.sase",
                "project_name": "sase",
                "workspace_num": 1,
                "workflow_name": "ace(run)-1",
                "cl_name": f"agent-{i}",
                "artifacts_timestamp": "20260928_120000",
                "started_at": "2026-09-28T09:32:28-04:00",
                "run_id": run_id,
            }
        )
    path.write_text(json.dumps(records))


def _proposals(count: int, clan: str | None = "toobig-@") -> list[dict]:
    items = []
    for i in range(count):
        item: dict = {
            "prompt": f"Do part {i}.",
            "workspace": "git:sase",
        }
        if clan is not None:
            item["clan"] = clan
        items.append(item)
    return items


def test_inflight_mid_launch_run() -> None:
    from sase.axe.state import find_inflight_chop_launches

    write_lumberjack_pid("run_every")
    _write_run("run_every", "toobig_split[sase]", "20260928T093200_850344")
    _write_result(
        "run_every",
        "toobig_split[sase]",
        "20260928T093200_850344",
        _proposals(61),
    )
    _write_records("run_every", "toobig_split[sase]", "20260928T093200_850344", 2)

    found = find_inflight_chop_launches()
    assert len(found) == 1
    run = found[0]
    assert run.lumberjack_name == "run_every"
    assert run.chop_name == "toobig_split[sase]"
    assert run.proposed_count == 61
    assert run.launched_count == 2
    assert run.clan == "toobig-@"
    assert run.remaining_count == 59
    assert "2/61" in run.summary_line()
    assert "59" in run.summary_line()


def test_job_script_phase_run_excluded() -> None:
    from sase.axe.state import find_inflight_chop_launches

    write_lumberjack_pid("run_every")
    _write_run("run_every", "split", "20260928T093200_000001")
    # No result file: still in job-script phase.
    _write_records("run_every", "split", "20260928T093200_000001", 0)

    assert find_inflight_chop_launches() == []


def test_fully_launched_run_excluded() -> None:
    from sase.axe.state import find_inflight_chop_launches

    write_lumberjack_pid("run_every")
    _write_run("run_every", "split", "20260928T093200_000002")
    _write_result(
        "run_every", "split", "20260928T093200_000002", _proposals(2, clan=None)
    )
    _write_records("run_every", "split", "20260928T093200_000002", 2)

    assert find_inflight_chop_launches() == []


def test_launched_status_run_excluded() -> None:
    from sase.axe.state import find_inflight_chop_launches

    write_lumberjack_pid("run_every")
    _write_run("run_every", "split", "20260928T093200_000003", status="launched")
    _write_result(
        "run_every", "split", "20260928T093200_000003", _proposals(3, clan=None)
    )
    _write_records("run_every", "split", "20260928T093200_000003", 1)

    assert find_inflight_chop_launches() == []


def test_dead_routine_pid_excluded() -> None:
    from sase.axe.state import find_inflight_chop_launches

    # A stale pid that is almost certainly not alive.
    pid_file = jack_state_dir() / "run_every" / "pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text("999999999")
    _write_run("run_every", "split", "20260928T093200_000004")
    _write_result(
        "run_every", "split", "20260928T093200_000004", _proposals(5, clan=None)
    )
    _write_records("run_every", "split", "20260928T093200_000004", 1)

    assert find_inflight_chop_launches() == []


def test_corrupt_json_skipped_without_raise() -> None:
    from sase.axe.state import find_inflight_chop_launches

    write_lumberjack_pid("run_every")
    _write_run("run_every", "split", "20260928T093200_000005")
    ensure_chop_dirs("run_every", "split")
    chop_run_result_path("run_every", "split", "20260928T093200_000005").write_text(
        "not json{"
    )
    _write_records("run_every", "split", "20260928T093200_000005", 0)

    assert find_inflight_chop_launches() == []
