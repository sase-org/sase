"""Focused tests for the chop runner's code-swap guards.

Each test runs a real shell job through ``run_configured_chop_once`` with the
real code-swap writer lock and last-swap stamp on the per-test SASE home. The
reproducer in ``tests/dev_update/test_swap_repro_chops.py`` drives the same
modes end to end through a live writer; these pin each classification, the
grace expiry, and the controls that must stay failures.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.axe import chop_swap_guard
from sase.axe.chop_runner import run_configured_chop_once
from sase.axe.chop_runner_types import ChopRunOutcome
from sase.axe.chop_script_runner import stream_chop_script
from sase.axe.config import AxeConfig, ChopConfig
from sase.axe.state import read_chop_run, read_chop_run_log_tail
from sase.dev_update.code_swap_lock import code_swap_writer_lock
from sase.dev_update.code_swap_stamp import (
    CODE_SWAP_GRACE_SECONDS,
    _last_code_swap_path,
)

from tests.axe_chop_runner_helpers import make_script

pytest_plugins = ["tests.axe_chop_runner_fixtures"]

_JOB = "swapguard_job"
_HOLDER = "sase dev update (pid 4242)"
_BINDING_FAILURE = (
    "echo \"ModuleNotFoundError: No module named 'sase_core_rs'\" >&2\nexit 1\n"
)
_SIGBUS = "ulimit -c 0\nkill -BUS $$\n"
_PLAIN_FAILURE = 'echo "ValueError: bad input" >&2\nexit 1\n'


@pytest.fixture
def scripts_config(tmp_path: Path) -> AxeConfig:
    (tmp_path / "scripts").mkdir(exist_ok=True)
    return AxeConfig(
        max_hook_runners=3,
        max_agent_runners=3,
        zombie_timeout_seconds=3600,
        query="",
        chop_script_dirs=[str(tmp_path / "scripts")],
    )


def _swap() -> None:
    """Run one real, instantaneous writer swap on the sandbox lock."""
    with code_swap_writer_lock() as lock:
        assert lock.acquired is True


def _write_stamp(*, completed_ago: float) -> None:
    completed = datetime.now(UTC) - timedelta(seconds=completed_ago)
    path = _last_code_swap_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "op": "install.dev",
                "pid": 1,
                "started_at": (completed - timedelta(seconds=5)).isoformat(),
                "completed_at": completed.isoformat(),
                "generation": 4,
            }
        ),
        encoding="utf-8",
    )


@contextmanager
def _swap_while_job_runs() -> Iterator[None]:
    """Complete a real swap after the job started and before it exits."""

    def _stream(*args: Any, **kwargs: Any) -> Any:
        _swap()
        return stream_chop_script(*args, **kwargs)

    with patch("sase.axe.chop_runner.stream_chop_script", _stream):
        yield


def _run(
    config: AxeConfig,
    *,
    holder_fn: Callable[[], str | None] | None = None,
) -> ChopRunOutcome:
    with patch("sase.axe.chop_runner.find_all_patches", return_value=[]):
        return run_configured_chop_once(
            lumberjack_name="hooks",
            chop=ChopConfig(name=_JOB, description=""),
            axe_config=config,
            source="scheduled",
            code_swap_writer_holder_fn=holder_fn,
        )


def _assert_inhibited(outcome: ChopRunOutcome) -> None:
    assert outcome.status == "skipped", (outcome.status, outcome.error)
    assert outcome.skip_reason == "inhibited"
    assert outcome.advances_cadence is False
    assert outcome.error is None
    assert outcome.reason is not None
    assert "retrying after the swap" in outcome.reason


def _entry_status(outcome: ChopRunOutcome) -> str:
    assert outcome.run_id is not None
    entry = read_chop_run("hooks", _JOB, outcome.run_id)
    assert entry is not None
    return entry.status


# -- no starts during a swap ------------------------------------------------


def test_live_writer_keeps_a_present_job_from_starting(
    temp_state_dir: Path, tmp_path: Path, scripts_config: AxeConfig
) -> None:
    marker = tmp_path / "ran"
    make_script(tmp_path, _JOB, f"touch {marker}\n")

    outcome = _run(scripts_config, holder_fn=lambda: _HOLDER)

    _assert_inhibited(outcome)
    assert outcome.reason is not None
    assert "did not start because a code swap is in progress" in outcome.reason
    assert _HOLDER in outcome.reason
    assert not marker.exists()
    assert _entry_status(outcome) == "skipped"
    assert outcome.run_id is not None
    assert _HOLDER in read_chop_run_log_tail("hooks", _JOB, outcome.run_id)


def test_real_live_writer_keeps_a_job_from_starting(
    temp_state_dir: Path, tmp_path: Path, scripts_config: AxeConfig
) -> None:
    marker = tmp_path / "ran"
    make_script(tmp_path, _JOB, f"touch {marker}\n")

    with code_swap_writer_lock() as lock:
        assert lock.acquired is True
        outcome = _run(scripts_config)

    _assert_inhibited(outcome)
    assert "sase dev update" in (outcome.reason or "")
    assert not marker.exists()


def test_job_runs_normally_once_the_writer_is_gone(
    temp_state_dir: Path, tmp_path: Path, scripts_config: AxeConfig
) -> None:
    make_script(tmp_path, _JOB, "echo ok\n")
    _swap()  # a completed swap never blocks a present script

    outcome = _run(scripts_config)

    assert outcome.status == "success"


# -- missing-script grace -----------------------------------------------------


def test_missing_script_inside_the_grace_is_an_inhibited_retry(
    temp_state_dir: Path, scripts_config: AxeConfig
) -> None:
    _write_stamp(completed_ago=CODE_SWAP_GRACE_SECONDS - 30)

    outcome = _run(scripts_config)

    _assert_inhibited(outcome)
    assert outcome.reason is not None
    assert "unavailable while a code swap settles" in outcome.reason
    assert "just install-dev swap #4" in outcome.reason
    assert _entry_status(outcome) == "skipped"


def test_missing_script_after_the_grace_is_a_loud_missing_script(
    temp_state_dir: Path, scripts_config: AxeConfig
) -> None:
    _write_stamp(completed_ago=CODE_SWAP_GRACE_SECONDS + 30)

    outcome = _run(scripts_config)

    assert outcome.status == "missing_script"
    assert outcome.advances_cadence is True
    assert _entry_status(outcome) == "missing_script"


def test_missing_script_grace_reason_tracks_the_clock() -> None:
    _write_stamp(completed_ago=0)
    now = datetime.now(UTC)
    assert chop_swap_guard.missing_script_grace_reason("s", now=now) is not None
    later = now + timedelta(seconds=CODE_SWAP_GRACE_SECONDS + 1)
    assert chop_swap_guard.missing_script_grace_reason("s", now=later) is None


# -- post-exit classification -------------------------------------------------


@pytest.mark.parametrize(
    ("body", "exit_code", "symptom"),
    [
        (_SIGBUS, -7, "died of SIGBUS"),
        (_BINDING_FAILURE, 1, "swap-skew import error"),
    ],
    ids=["sigbus", "missing-binding"],
)
def test_failure_from_a_swap_during_the_run_is_an_inhibited_retry(
    temp_state_dir: Path,
    tmp_path: Path,
    scripts_config: AxeConfig,
    body: str,
    exit_code: int,
    symptom: str,
) -> None:
    make_script(tmp_path, _JOB, body)

    with _swap_while_job_runs():
        outcome = _run(scripts_config)

    _assert_inhibited(outcome)
    assert outcome.exit_code == exit_code
    assert symptom in (outcome.reason or "")
    assert "after overlapping a code swap" in (outcome.reason or "")
    assert outcome.run_id is not None
    entry = read_chop_run("hooks", _JOB, outcome.run_id)
    assert entry is not None
    assert entry.status == "skipped"
    assert entry.exit_code == exit_code  # kept for forensics
    assert entry.error is None
    assert entry.reason == outcome.reason
    assert "retrying after the swap" in read_chop_run_log_tail(
        "hooks", _JOB, outcome.run_id
    )


def test_failure_with_a_writer_live_at_exit_is_an_inhibited_retry(
    temp_state_dir: Path, tmp_path: Path, scripts_config: AxeConfig
) -> None:
    make_script(tmp_path, _JOB, _BINDING_FAILURE)
    probes: list[str | None] = [None, _HOLDER]  # absent at start, live at exit

    outcome = _run(scripts_config, holder_fn=lambda: probes.pop(0))

    _assert_inhibited(outcome)
    assert f"still in progress: {_HOLDER}" in (outcome.reason or "")
    assert probes == []


@pytest.mark.parametrize(
    ("body", "exit_code"),
    [(_SIGBUS, -7), (_BINDING_FAILURE, 1)],
    ids=["sigbus", "missing-binding"],
)
def test_failure_after_an_earlier_swap_stays_a_failure(
    temp_state_dir: Path,
    tmp_path: Path,
    scripts_config: AxeConfig,
    body: str,
    exit_code: int,
) -> None:
    """A swap that completed before the run started did not overlap it."""
    make_script(tmp_path, _JOB, body)
    _swap()

    outcome = _run(scripts_config)

    assert outcome.status == "failure"
    assert outcome.exit_code == exit_code
    assert outcome.error is not None
    assert _entry_status(outcome) == "failure"


def test_unrelated_failure_during_a_swap_stays_a_failure(
    temp_state_dir: Path, tmp_path: Path, scripts_config: AxeConfig
) -> None:
    """Overlap alone is not enough: the failure must look like swap fallout."""
    make_script(tmp_path, _JOB, _PLAIN_FAILURE)

    with _swap_while_job_runs():
        outcome = _run(scripts_config)

    assert outcome.status == "failure"
    assert outcome.exit_code == 1


def test_overlapping_exit_reason_ignores_success_and_missing_codes() -> None:
    now = datetime.now(UTC)
    for exit_code in (None, 0):
        assert (
            chop_swap_guard.overlapping_exit_reason(
                chop_name=_JOB,
                exit_code=exit_code,
                output="No module named 'sase_core_rs'",
                started_at=now,
                finished_at=now,
                holder_fn=lambda: _HOLDER,
            )
            is None
        )


def test_probe_failures_read_as_no_swap() -> None:
    def _boom() -> str | None:
        raise RuntimeError("probe exploded")

    assert chop_swap_guard.probe_writer(_boom) is None
    _last_code_swap_path().parent.mkdir(parents=True, exist_ok=True)
    _last_code_swap_path().write_text("{broken", encoding="utf-8")
    now = datetime.now(UTC)
    assert chop_swap_guard.missing_script_grace_reason("s") is None
    assert (
        chop_swap_guard.overlapping_exit_reason(
            chop_name=_JOB,
            exit_code=-7,
            output=None,
            started_at=now - timedelta(seconds=5),
            finished_at=now,
            holder_fn=_boom,
        )
        is None
    )
