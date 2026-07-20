"""Tests for free-standing async work that must not occupy Textual's pump."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from sase.ace.tui.util import pump_tasks
from sase.ace.tui.util.pump_tasks import (
    cancel_pump_free_tasks,
    spawn_pump_free_task,
)


@pytest.mark.asyncio
async def test_spawn_retains_names_and_prunes_completed_task() -> None:
    owner = SimpleNamespace()
    release = asyncio.Event()

    async def _work() -> int:
        await release.wait()
        return 7

    task = spawn_pump_free_task(
        owner,
        _work(),
        name="sase-test-pump-free",
        registry_attr="_test_tasks",
    )

    assert task is not None
    assert task.get_name() == "sase-test-pump-free"
    assert owner._test_tasks == {task}
    release.set()
    assert await task == 7
    await asyncio.sleep(0)
    assert owner._test_tasks == set()


@pytest.mark.asyncio
async def test_cancel_cancels_every_registered_task() -> None:
    owner = SimpleNamespace()

    async def _wait_forever() -> None:
        await asyncio.Event().wait()

    first = spawn_pump_free_task(
        owner,
        _wait_forever(),
        name="sase-test-first",
        registry_attr="_first_tasks",
    )
    second = spawn_pump_free_task(
        owner,
        _wait_forever(),
        name="sase-test-second",
        registry_attr="_second_tasks",
    )
    assert first is not None and second is not None

    cancel_pump_free_tasks(owner)
    await asyncio.gather(first, second, return_exceptions=True)

    assert first.cancelled()
    assert second.cancelled()


@pytest.mark.asyncio
async def test_repeated_failure_logs_one_traceback_then_periodic_count(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Identical pump-task failures do not emit a traceback every tick."""
    owner = SimpleNamespace()
    clock = iter((0.0, 1.0, 301.0))
    monkeypatch.setattr(pump_tasks, "monotonic", lambda: next(clock))
    pump_tasks._failure_log_states.clear()
    caplog.set_level(logging.ERROR, logger=pump_tasks.__name__)

    async def _fail() -> None:
        raise ValueError("same failure")

    for _ in range(3):
        task = spawn_pump_free_task(
            owner,
            _fail(),
            name="sase-test-failure",
            registry_attr="_test_tasks",
        )
        assert task is not None
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)

    records = [
        record
        for record in caplog.records
        if "pump-free task sase-test-failure" in record.getMessage()
    ]
    assert len(records) == 2
    assert sum(record.exc_info is not None for record in records) == 1
    assert "repeated failure 2 time(s)" in records[-1].getMessage()
    assert "ValueError: same failure" in records[-1].getMessage()
