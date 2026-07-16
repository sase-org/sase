"""Tests for free-standing async work that must not occupy Textual's pump."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

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
