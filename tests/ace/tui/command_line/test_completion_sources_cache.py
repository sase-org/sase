"""Provider-cache tests for the ``:`` Command Line.

Fresh caches: the provider disk cache is bypassed after a block finishes
and stale in-flight fetches are dropped.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.command_line.sources import ProviderCache

from tests.ace.tui.command_line._completion_sources_shared import (
    await_provider_task,
    panel,
    shown,
    stub_provider,
    type_line,
)

pytest_plugins = ["tests.ace.tui.command_line._completion_sources_shared"]

__all__ = [
    "test_finishing_a_command_drops_the_stale_in_flight_fetch",
    "test_finishing_a_command_refetches_past_the_disk_cache",
    "test_finishing_a_command_under_an_active_menu_refetches_on_next_render",
    "test_invalidate_retires_in_flight_fetches_and_distrusts_the_disk_cache",
]


def test_invalidate_retires_in_flight_fetches_and_distrusts_the_disk_cache() -> None:
    """A finished command voids in-flight results and the providers' disk cache."""
    cache = ProviderCache(ttl_seconds=60.0)
    assert cache.bypass_disk_cache("pending_plan", None) is False

    in_flight = cache.next_generation()
    cache.invalidate()
    assert cache.commit(in_flight, "pending_plan", None, [{"value": "stale"}]) is False
    assert cache.cached("pending_plan", None) is None
    assert cache.bypass_disk_cache("pending_plan", None) is True
    assert cache.bypass_disk_cache("bead", None) is True

    refetch = cache.next_generation()
    assert cache.commit(refetch, "pending_plan", None, [{"value": "fresh"}]) is True
    # One fresh fetch per slot is enough: the disk file was rewritten by it.
    assert cache.bypass_disk_cache("pending_plan", None) is False
    assert cache.bypass_disk_cache("bead", None) is True
    cache.invalidate()
    assert cache.bypass_disk_cache("pending_plan", None) is True


def _project(screen: Any) -> str | None:
    return screen._working_context.project if screen._working_context else None


def _finish_command(page: Any, line: str) -> None:
    """Deliver an exit completion for a running block of *line*."""
    from sase.ace.tui.command_line.exits import deliver_command_line_exit
    from sase.ace.tui.command_line.session import (
        CommandLineBlock,
        command_line_session_for,
    )

    command_line_session_for(page.app).blocks.append(
        CommandLineBlock(
            block_id="b-finish", line=line, status="running", proc_id="proc-finish"
        )
    )
    completion = SimpleNamespace(proc_id="proc-finish", exit_code=0, status="done")
    assert deliver_command_line_exit(page.app, completion) is True


async def test_finishing_a_command_refetches_past_the_disk_cache(
    grammar_handle: Any, history_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``plan approve X`` then ``plan approve <Tab>`` must not offer ``X`` again."""
    from sase.completion.candidates.protocol import Candidate

    pending = [Candidate("alpha-plan", "a plan")]
    uses_disk_cache = stub_provider(monkeypatch, lambda kind: list(pending))
    async with panel(grammar_handle) as (page, screen):
        await type_line(page, screen, "plan approve ")
        await await_provider_task(screen)
        assert uses_disk_cache == [True]
        assert "alpha-plan" in shown(screen)

        pending.clear()
        _finish_command(page, "plan approve alpha-plan")
        await await_provider_task(screen)
        assert uses_disk_cache == [True, False]
        assert "alpha-plan" not in shown(screen)
        # The fresh fetch rewrote the disk file, so later fetches trust it again.
        assert not screen._provider_cache.bypass_disk_cache(
            "pending_plan", _project(screen)
        )


async def test_finishing_a_command_drops_the_stale_in_flight_fetch(
    grammar_handle: Any, history_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fetch started before the finish cannot put its rows back in the cache."""
    from sase.completion.candidates.protocol import Candidate

    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def _fetch(kind: str) -> list[Candidate]:
        calls.append(kind)
        if len(calls) == 1:
            started.set()
            release.wait(timeout=5)
            return [Candidate("stale-plan", "")]
        return [Candidate("fresh-plan", "")]

    uses_disk_cache = stub_provider(monkeypatch, _fetch)
    async with panel(grammar_handle) as (page, screen):
        await type_line(page, screen, "plan approve ")
        first = screen._provider_task
        assert first is not None
        await page.wait_for(lambda _state: started.is_set())

        _finish_command(page, "plan approve stale-plan")
        release.set()
        await await_provider_task(screen)
        await asyncio.gather(first, return_exceptions=True)

        cached = screen._provider_cache.cached("pending_plan", _project(screen))
        assert [row["value"] for row in cached or []] == ["fresh-plan"]
        assert uses_disk_cache == [True, False]


async def test_finishing_a_command_under_an_active_menu_refetches_on_next_render(
    grammar_handle: Any, history_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The menu keeps its rows, but the very next render fetches fresh ones."""
    from sase.completion.candidates.protocol import Candidate

    uses_disk_cache = stub_provider(
        monkeypatch,
        lambda kind: [Candidate("alpha-plan", ""), Candidate("beta-plan", "")],
    )
    async with panel(grammar_handle) as (page, screen):
        await type_line(page, screen, "plan approve ")
        await await_provider_task(screen)
        await page.press("tab")
        assert screen._popup_state.menu_active

        _finish_command(page, "plan approve gamma-plan")
        assert screen._popup_state.menu_active
        assert screen._provider_task is None  # nothing repainted under the menu
        assert uses_disk_cache == [True]

        screen._refresh_completion()  # the next render
        await await_provider_task(screen)
        assert uses_disk_cache == [True, False]
