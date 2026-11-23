"""In-place apply coverage for bead warmup results."""

from __future__ import annotations

import pytest

from sase.ace.tui.actions.agents._loading_bead_warmup_types import (
    AgentBeadWarmupResults,
)
from sase.ace.tui.agent_completion import (
    WaitBeadStatusCounts,
    WaitDependencyStatusCounts,
)
from sase.ace.tui.models.agent_wait_beads import _WAIT_BEAD_STATUS_CACHE
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from tests.ace.tui._agents_bead_warmup_helpers import (
    FakeApp,
    clear_bead_display_cache,
    make_agent,
)

pytestmark = pytest.mark.usefixtures("clear_bead_display_cache")

__all__ = [
    "test_apply_noop_without_results",
    "test_apply_patches_only_result_rows",
    "test_apply_patches_rows_losing_confirmed_bead",
    "test_apply_rematches_current_object_by_identity",
    "test_apply_wait_bead_status_results_keeps_singleton_id_and_adds_warm_glyph",
    "test_apply_wait_bead_status_results_passes_fresh_count_override",
    "test_apply_wait_bead_status_results_rebuilds_once_on_patch_failure",
]


def test_apply_patches_only_result_rows() -> None:
    app = FakeApp()
    confirmed = make_agent(agent_name="sase-x.3", cl_name="confirmed", raw_suffix="1")
    other = make_agent(agent_name="sase-y.4", cl_name="other", raw_suffix="2")
    app._agents = [confirmed, other]
    app._agents_with_children = [confirmed, other]

    app._apply_bead_warmup_results(
        AgentBeadWarmupResults({confirmed.identity: True}, set())
    )

    assert app._patched == [confirmed]


def test_apply_patches_rows_losing_confirmed_bead() -> None:
    app = FakeApp()
    removed = make_agent(agent_name="sase-x.3", cl_name="removed", raw_suffix="1")
    other = make_agent(agent_name="sase-y.4", cl_name="other", raw_suffix="2")
    app._agents = [removed, other]
    app._agents_with_children = [removed, other]

    app._apply_bead_warmup_results(
        AgentBeadWarmupResults({removed.identity: False}, set())
    )

    assert app._patched == [removed]


def test_apply_rematches_current_object_by_identity() -> None:
    """A refresh may rebuild the list; the patch lands on the live object."""
    app = FakeApp()
    snapshot = make_agent(agent_name="sase-x.3", cl_name="feat", raw_suffix="1")
    rebuilt = make_agent(agent_name="sase-x.3", cl_name="feat", raw_suffix="1")
    app._agents = [rebuilt]
    app._agents_with_children = [rebuilt]

    app._apply_bead_warmup_results(
        AgentBeadWarmupResults({snapshot.identity: True}, set())
    )

    assert app._patched == [rebuilt]


def test_apply_noop_without_results() -> None:
    app = FakeApp()
    app._agents = [make_agent()]

    app._apply_bead_warmup_results(AgentBeadWarmupResults({}, set()))

    assert app._patched == []


def test_apply_wait_bead_status_results_passes_fresh_count_override() -> None:
    app = FakeApp()
    waiter = make_agent(
        status="WAITING",
        waiting_for_beads=["sase-1"],
        cl_name="waiter",
        raw_suffix="waiter",
    )
    _WAIT_BEAD_STATUS_CACHE.set(("proj", "sase-1"), "closed")
    app._agents = [waiter]
    app._agents_with_children = [waiter]

    app._apply_bead_warmup_results(AgentBeadWarmupResults({}, {waiter.identity}))

    assert app._patched == [waiter]
    assert app._patch_kwargs == [
        {
            "wait_dependency_counts": WaitDependencyStatusCounts(
                beads=WaitBeadStatusCounts(closed=1)
            )
        }
    ]


def test_apply_wait_bead_status_results_keeps_singleton_id_and_adds_warm_glyph() -> (
    None
):
    app = FakeApp()
    waiter = make_agent(
        status="WAITING",
        waiting_for_beads=["sase-1"],
        cl_name="waiter",
        raw_suffix="waiter",
    )
    cold_left, _, _ = format_agent_option(waiter, 0, is_selected=False)
    _WAIT_BEAD_STATUS_CACHE.set(("proj", "sase-1"), "in_progress")
    app._agents = [waiter]
    app._agents_with_children = [waiter]

    app._apply_bead_warmup_results(AgentBeadWarmupResults({}, {waiter.identity}))

    assert "waiter (WAITING sase-1)" in cold_left.plain
    assert app._patched == [waiter]
    assert app._patch_kwargs == [
        {
            "wait_dependency_counts": WaitDependencyStatusCounts(
                beads=WaitBeadStatusCounts(in_progress=1)
            )
        }
    ]
    wait_counts = app._patch_kwargs[0]["wait_dependency_counts"]
    assert isinstance(wait_counts, WaitDependencyStatusCounts)
    warm_left, _, _ = format_agent_option(
        waiter,
        0,
        is_selected=False,
        wait_dependency_counts=wait_counts,
    )
    assert "waiter (WAITING ◐ sase-1)" in warm_left.plain


def test_apply_wait_bead_status_results_rebuilds_once_on_patch_failure() -> None:
    app = FakeApp()
    app._patch_success = False
    first = make_agent(
        status="WAITING",
        waiting_for_beads=["a"],
        cl_name="first",
        raw_suffix="first",
    )
    second = make_agent(
        status="WAITING",
        waiting_for_beads=["b"],
        cl_name="second",
        raw_suffix="second",
    )
    _WAIT_BEAD_STATUS_CACHE.set(("proj", "a"), "closed")
    _WAIT_BEAD_STATUS_CACHE.set(("proj", "b"), "open")
    app._agents = [first, second]
    app._agents_with_children = [first, second]

    app._apply_bead_warmup_results(
        AgentBeadWarmupResults({}, {first.identity, second.identity})
    )

    assert app._patched == [first, second]
    assert app._refresh_calls == [{"list_changed": True, "defer_detail": True}]
