"""Tests for releasing a parked runner's retained bootstrap memory."""

from __future__ import annotations

import ctypes
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.axe import runner_idle_memory
from sase.axe.run_agent_wait import wait_for_dependencies
from sase.axe.run_agent_wait_slots import wait_for_runner_slot


@pytest.fixture(autouse=True)
def _reset_trim_cache() -> Iterator[None]:
    """Clear the cached libc lookup so each test resolves it on its own terms."""
    runner_idle_memory._malloc_trim = None
    runner_idle_memory._resolved = False
    yield
    runner_idle_memory._malloc_trim = None
    runner_idle_memory._resolved = False


def test_release_collects_and_trims_when_glibc_provides_the_symbol() -> None:
    trim = MagicMock(return_value=1)

    with (
        patch.object(runner_idle_memory.gc, "collect") as collect,
        patch.object(runner_idle_memory, "_resolve_malloc_trim", return_value=trim),
    ):
        assert runner_idle_memory.release_idle_memory() is True

    collect.assert_called_once_with()
    trim.assert_called_once_with(0)


def test_release_reports_false_when_trim_frees_nothing() -> None:
    """glibc returning 0 means nothing moved, which is not a failure."""
    with patch.object(
        runner_idle_memory,
        "_resolve_malloc_trim",
        return_value=MagicMock(return_value=0),
    ):
        assert runner_idle_memory.release_idle_memory() is False


def test_release_still_collects_where_there_is_no_malloc_trim() -> None:
    """macOS and musl have no such symbol; the collect half must still run."""
    with (
        patch.object(runner_idle_memory.gc, "collect") as collect,
        patch.object(runner_idle_memory, "_resolve_malloc_trim", return_value=None),
    ):
        assert runner_idle_memory.release_idle_memory() is False

    collect.assert_called_once_with()


def test_release_never_propagates_a_failing_trim() -> None:
    """A runner that cannot trim must keep waiting, not die inside the barrier."""
    with patch.object(
        runner_idle_memory,
        "_resolve_malloc_trim",
        return_value=MagicMock(side_effect=OSError("boom")),
    ):
        assert runner_idle_memory.release_idle_memory() is False


def test_non_linux_hosts_never_probe_libc() -> None:
    with (
        patch.object(runner_idle_memory.sys, "platform", "darwin"),
        patch.object(runner_idle_memory.ctypes, "CDLL") as cdll,
    ):
        assert runner_idle_memory._resolve_malloc_trim() is None

    cdll.assert_not_called()


def test_a_libc_without_the_symbol_resolves_to_none() -> None:
    libc = MagicMock(spec=[])  # no malloc_trim attribute
    with (
        patch.object(runner_idle_memory.sys, "platform", "linux"),
        patch.object(runner_idle_memory.ctypes, "CDLL", return_value=libc),
    ):
        assert runner_idle_memory._resolve_malloc_trim() is None


def test_resolution_is_cached_across_calls() -> None:
    """A wait loop calls this repeatedly; loading libc each poll would cost more."""
    libc = MagicMock()
    libc.malloc_trim = MagicMock(spec=ctypes.CDLL(None).__class__)

    with (
        patch.object(runner_idle_memory.sys, "platform", "linux"),
        patch.object(runner_idle_memory.ctypes, "CDLL", return_value=libc) as cdll,
    ):
        first = runner_idle_memory._resolve_malloc_trim()
        second = runner_idle_memory._resolve_malloc_trim()

    assert first is second
    cdll.assert_called_once()


def _waiter(base: Path) -> Path:
    artifact_dir = base / "artifacts" / "waiter"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "agent_meta.json").write_text('{"pid": 123}', encoding="utf-8")
    return artifact_dir


def test_parking_for_a_duration_releases_the_bootstrap_peak(tmp_path: Path) -> None:
    waiter_dir = _waiter(tmp_path)

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch("sase.axe.run_agent_wait.time.sleep"),
        patch("sase.axe.run_agent_wait.release_idle_memory") as release,
    ):
        blocked = wait_for_dependencies(
            [],
            str(waiter_dir),
            "cl",
            "20260513120000",
            {"pid": 123},
            duration=1.0,
        )

    assert blocked is True
    release.assert_called_once_with()


def test_a_wait_that_never_parks_does_not_trim(tmp_path: Path) -> None:
    """The fast path is about to run the agent, so its memory is about to matter."""
    waiter_dir = _waiter(tmp_path)

    with (
        patch("sase.axe.run_agent_wait.was_killed", return_value=False),
        patch("sase.axe.run_agent_wait.release_idle_memory") as release,
    ):
        blocked = wait_for_dependencies(
            ["dep"],
            str(waiter_dir),
            "cl",
            "20260513120000",
            {"pid": 123, "wait_completed_at": "2026-09-12T06:00:00-04:00"},
            project_name="proj",
        )

    assert blocked is False
    release.assert_not_called()


def test_queueing_for_a_runner_slot_releases_the_bootstrap_peak() -> None:
    claims = [(None, True), ("2026-09-12T06:00:00-04:00", False)]

    with (
        patch(
            "sase.axe.run_agent_wait_slots._try_claim_runner_slot",
            side_effect=claims,
        ),
        patch(
            "sase.axe.run_agent_wait_slots.advance_runner_slot_poll",
            return_value=(0, "token"),
        ),
        patch(
            "sase.axe.run_agent_wait_slots.runner_slot_state_token",
            return_value="token",
        ),
        patch("sase.axe.run_agent_wait_slots.was_killed", return_value=False),
        patch("sase.axe.run_agent_wait_slots.release_idle_memory") as release,
    ):
        started = wait_for_runner_slot(
            "/tmp/artifacts",
            "cl",
            "20260513120000",
            {"pid": 123},
            wait_runners=None,
            claim=lambda: "2026-09-12T06:00:00-04:00",
        )

    assert started == "2026-09-12T06:00:00-04:00"
    release.assert_called_once_with()


def test_claiming_a_slot_immediately_does_not_trim() -> None:
    with (
        patch(
            "sase.axe.run_agent_wait_slots._try_claim_runner_slot",
            return_value=("2026-09-12T06:00:00-04:00", False),
        ),
        patch(
            "sase.axe.run_agent_wait_slots.runner_slot_state_token",
            return_value="token",
        ),
        patch("sase.axe.run_agent_wait_slots.was_killed", return_value=False),
        patch("sase.axe.run_agent_wait_slots.release_idle_memory") as release,
    ):
        wait_for_runner_slot(
            "/tmp/artifacts",
            "cl",
            "20260513120000",
            {"pid": 123},
            wait_runners=None,
            claim=lambda: "2026-09-12T06:00:00-04:00",
        )

    release.assert_not_called()
