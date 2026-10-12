"""Archive-controller tests: prewarm gate and idle ticks (no flag gate)."""

from __future__ import annotations

import pytest

from sase.ace.tui.actions.agents._archive_controller import (
    archive_corpus_snapshot,
    archive_inbox_pulse,
    note_inbox_applied_for_archive,
    note_inbox_load_finished_for_archive,
    request_archive_view_load,
    schedule_archive_idle_tick,
)
from sase.ace.tui.actions.agents._archive_view import open_agents_archive_view
from sase.ace.tui.models.agent_archive_controller import (
    ARCHIVE_CORPUS_LOADING,
    ARCHIVE_CORPUS_WARM,
)
from sase.ace.tui.models.agent_archive_view import AGENTS_VIEW_ARCHIVE
from sase.ace.tui.util.nav_gate import NavigationGate
from sase.feature_flags import override_flags
from tests.ace.tui._agent_archive_controller_helpers import (
    bounded_load,
    complete_load,
    instrument,
    make_agent,
    make_owner,
)

__all__ = [
    "test_bounded_inbox_load_does_not_open_prewarm_gate",
    "test_complete_idle_prewarms_once_and_idle_tick_skips_compile",
    "test_early_open_paints_loading_and_queues_until_gate",
    "test_hooks_probe_and_prewarm_without_a_flag",
    "test_inbox_load_scheduled_resets_on_apply_and_failure",
    "test_prewarm_waits_for_idle_ui",
    "test_prompt_typing_defers_idle_requery",
]


@pytest.mark.asyncio
async def test_hooks_probe_and_prewarm_without_a_flag() -> None:
    owner = make_owner(agents=[make_agent("live")])
    spawn, compile_calls, facet_calls = instrument(owner)

    with override_flags():
        note_inbox_applied_for_archive(owner, load_state=complete_load())
        assert spawn.coros
        await spawn.drain()
        assert len(compile_calls) == 1
        assert facet_calls == ["facets"]
        schedule_archive_idle_tick(owner)
        await spawn.drain()
        request_archive_view_load(owner)
        outcome = open_agents_archive_view(owner)

    assert outcome.status == "opened"
    assert outcome.view == AGENTS_VIEW_ARCHIVE
    assert owner._agents[0].cl_name == "live"


def test_bounded_inbox_load_does_not_open_prewarm_gate() -> None:
    owner = make_owner(agents=[make_agent("live")])
    spawn, compile_calls, _facets = instrument(owner)

    note_inbox_applied_for_archive(owner, load_state=bounded_load())
    schedule_archive_idle_tick(owner)

    assert compile_calls == []
    assert spawn.coros == []
    assert archive_corpus_snapshot(owner).status == "cold"


@pytest.mark.asyncio
async def test_early_open_paints_loading_and_queues_until_gate() -> None:
    owner = make_owner(agents=[make_agent("live")])
    spawn, compile_calls, _facets = instrument(owner)

    outcome = open_agents_archive_view(owner)
    assert outcome.status == "opened"
    assert archive_corpus_snapshot(owner).status == ARCHIVE_CORPUS_LOADING
    assert compile_calls == []
    assert owner._schedule_calls == ["archive_prewarm_gate"]

    note_inbox_applied_for_archive(owner, load_state=complete_load())
    assert compile_calls == []
    await spawn.drain()

    assert compile_calls
    assert archive_corpus_snapshot(owner).warm
    assert owner._agents[0].cl_name == "live"


@pytest.mark.asyncio
async def test_complete_idle_prewarms_once_and_idle_tick_skips_compile() -> None:
    owner = make_owner(agents=[make_agent("live", "RUNNING")])
    spawn, compile_calls, facet_calls = instrument(owner)

    note_inbox_applied_for_archive(owner, load_state=complete_load())
    assert spawn.coros
    await spawn.drain()
    assert len(compile_calls) == 1
    assert facet_calls == ["facets"]
    pulse = archive_inbox_pulse(owner)
    assert pulse.total == 1
    assert pulse.running == 1

    schedule_archive_idle_tick(owner)
    await spawn.drain()

    assert len(compile_calls) == 1
    assert facet_calls == ["facets"]
    assert archive_corpus_snapshot(owner).status == ARCHIVE_CORPUS_WARM


@pytest.mark.asyncio
async def test_prewarm_waits_for_idle_ui() -> None:
    owner = make_owner()
    spawn, compile_calls, _facets = instrument(owner)
    owner._nav_gate.record()

    note_inbox_applied_for_archive(owner, load_state=complete_load())
    assert spawn.coros == []
    owner._nav_gate = NavigationGate()
    schedule_archive_idle_tick(owner)
    await spawn.drain()

    assert compile_calls


@pytest.mark.asyncio
async def test_prompt_typing_defers_idle_requery() -> None:
    owner = make_owner()
    spawn, compile_calls, _facets = instrument(owner)

    note_inbox_applied_for_archive(owner, load_state=complete_load())
    await spawn.drain()
    owner._prompt_input_active = lambda: True
    schedule_archive_idle_tick(owner)

    assert spawn.coros == []
    assert len(compile_calls) == 1


@pytest.mark.asyncio
async def test_inbox_load_scheduled_resets_on_apply_and_failure() -> None:
    owner = make_owner()
    instrument(owner)

    request_archive_view_load(owner)
    assert owner._agents_archive_controller.inbox_load_scheduled is True
    assert owner._schedule_calls == ["archive_prewarm_gate"]
    note_inbox_applied_for_archive(owner, load_state=bounded_load())
    assert owner._agents_archive_controller.inbox_load_scheduled is False
    request_archive_view_load(owner)
    assert owner._agents_archive_controller.inbox_load_scheduled is True
    note_inbox_load_finished_for_archive(owner)
    assert owner._agents_archive_controller.inbox_load_scheduled is False
    request_archive_view_load(owner)

    assert owner._schedule_calls == [
        "archive_prewarm_gate",
        "archive_prewarm_gate",
        "archive_prewarm_gate",
    ]
