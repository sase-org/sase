"""Row traversals must not close reference cycles around the rows they visit.

Every presentation walker used to be a self-recursive local function. Its
closure cell referenced the function that referenced the cell, so each call
left a cycle that pinned every visited row (and the walker's result) until the
cyclic collector ran. These tests pin both halves of the fix:

* the walkers still visit rows in exactly the same order, dedupe the same way,
  and terminate on a malformed graph with a loop (checked while the rows are
  alive); and
* dropping the result frees the rows and the walker's state by refcount alone,
  verified under ``gc.DEBUG_SAVEALL`` with the shared
  :mod:`tests.ace.tui._gc_cycles` helper.

Each SAVEALL producer builds a fresh row graph per call, like one refresh
cycle does, so a retained cycle shows up as ``Agent`` garbage.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

import pytest

from sase.ace.tui.actions.agents._confirmation_sase_agents import _loaded_tree_rows
from sase.ace.tui.models._agent_ordering import sort_and_reorder
from sase.ace.tui.models._agent_status_apply import _descendant_agent_session_turns
from sase.ace.tui.models._agent_time_aggregate import _collect_aggregate_member_rows
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models._agent_tree_clan import _assign_clan_tree_links
from sase.ace.tui.models._fold_filter import filter_agents_by_fold_state
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_question_rounds import _walk_own_turns
from sase.ace.tui.models.agent_session_members import (
    concrete_agent_session_turn_rows,
)
from sase.ace.tui.models.agent_tribe_summary import _descendant_rows
from sase.ace.tui.models.fold_state import FoldStateManager
from sase.ace.tui.widgets._agent_list_helpers import ordered_row_providers
from sase.ace.tui.widgets.prompt_panel._agent_display_hint_cache import (
    _source_digest_parts,
)
from tests.ace.tui._gc_cycles import AGENT_TYPE, measure_cycle_garbage
from tests.ace.tui.models._agent_session_members_helpers import (
    make_agent,
    make_gate_member,
    make_monitor_member,
)

__all__: list[str] = []


@dataclass(frozen=True)
class _Graph:
    """A session container with aliases, duplicates, an excluded row and a loop."""

    root: Agent
    coder: Agent
    monitor: Agent
    gate: Agent
    duplicate: Agent
    parallel: Agent


def _graph(*, loop: bool = True) -> _Graph:
    """Build one fresh row graph.

    ``root`` links ``coder`` (runtime) and ``monitor``/``duplicate``/``parallel``
    (followups). ``coder`` links the same ``monitor`` again (an alias) and, with
    ``loop``, back to ``root``. ``duplicate`` is a distinct object carrying
    ``coder``'s durable identity, and ``gate`` nests under ``monitor``. The
    retention producers pass ``loop=False``: a loop is itself a reference cycle
    in the input, which would be garbage no matter how the walker behaves.
    """
    root = make_agent("alpha--0", role="root")
    coder = make_agent(
        "alpha--code", role="code", parent_timestamp=root.raw_suffix, start_offset=1
    )
    monitor = make_monitor_member(
        "alpha--mon", root=root, monitor_id="m1", monitor_state="running"
    )
    gate = make_gate_member(
        "alpha--gate", root=monitor, gate_id="g1", gate_state="pending"
    )
    duplicate = make_agent(
        "alpha--code", role="code", parent_timestamp=root.raw_suffix, start_offset=1
    )
    parallel = make_agent(
        "alpha--par", role="code", parent_timestamp=root.raw_suffix, start_offset=2
    )
    parallel.agent_session_parallel = True
    root.runtime_children = [coder]
    root.followup_agents = [monitor, duplicate, parallel]
    coder.followup_agents = [monitor, root] if loop else [monitor]
    monitor.runtime_children = [gate]
    return _Graph(root, coder, monitor, gate, duplicate, parallel)


def _names(rows: Sequence[Agent]) -> list[str]:
    return [row.cl_name for row in rows]


def _suffix(row: Agent) -> str:
    assert row.raw_suffix is not None
    return row.raw_suffix


# --------------------------------------------------------------------------- #
# Order, dedupe and loop safety while the rows are alive.
# --------------------------------------------------------------------------- #


def test_session_turn_expansion_keeps_causal_order_dedupe_and_exclusions() -> None:
    g = _graph()

    rows = concrete_agent_session_turn_rows(g.root)

    # The monitor (and the gate nested under it) attach to the container root
    # first; the duplicate-identity row, the aliased link, the excluded
    # parallel row and the loop back to the root add nothing.
    assert _names(rows) == ["alpha--0", "alpha--mon", "alpha--gate", "alpha--code"]
    assert rows[3] is g.coder


def test_session_turn_expansion_walks_through_plain_rows_to_nested_turns() -> None:
    root = make_agent("alpha--0", role="root")
    coder = make_agent(
        "alpha--code", role="code", parent_timestamp=root.raw_suffix, start_offset=1
    )
    helper = make_agent(
        "alpha--helper",
        role="code",
        parent_timestamp=coder.raw_suffix,
        start_offset=2,
        workflow_child=True,
        step_type="bash",
    )
    monitor = make_monitor_member(
        "alpha--mon", root=helper, monitor_id="m1", monitor_state="running"
    )
    root.runtime_children = [coder]
    coder.followup_agents = [helper]
    helper.followup_agents = [monitor, helper]  # loops back to itself

    assert _names(concrete_agent_session_turn_rows(root)) == [
        "alpha--0",
        "alpha--code",
        "alpha--mon",
    ]


def test_source_digest_parts_visit_followups_depth_first_once() -> None:
    g = _graph()
    g.root.followup_agents = [g.coder, g.monitor]
    g.coder.followup_agents = [g.gate, g.root]
    g.monitor.followup_agents = [g.gate, g.coder]

    parts = _source_digest_parts(g.root)

    identities = [value for label, value in parts if label == "identity"]
    assert identities == [
        g.root.identity,
        g.coder.identity,
        g.gate.identity,
        g.monitor.identity,
    ]
    assert len(parts) == 9 * len(identities)


def test_own_turn_walk_is_depth_first_runtime_then_followup() -> None:
    g = _graph()

    rows = _walk_own_turns(g.root)

    # ``coder`` is first and its subtree (monitor, gate) precedes the root's
    # own followups; the duplicate shares ``coder``'s identity and is skipped,
    # the parallel row is not excluded here, and the loop back to the root
    # ends the walk.
    assert _names(rows) == [
        "alpha--0",
        "alpha--code",
        "alpha--mon",
        "alpha--gate",
        "alpha--par",
    ]


def test_descendant_rows_skip_clan_containers_and_dedupe_identity() -> None:
    g = _graph()
    clan = make_agent("clanbox", role="code", parent_timestamp=g.root.raw_suffix)
    clan.is_clan_container = True
    clan.followup_agents = [make_agent("hidden-under-clan", role="code")]
    g.root.followup_agents.append(clan)

    rows = _descendant_rows(g.root)

    assert _names(rows) == [
        "alpha--code",
        "alpha--mon",
        "alpha--gate",
        "alpha--0",
        "alpha--par",
    ]


def test_descendant_session_turns_collect_only_turns_through_plain_rows() -> None:
    g = _graph()
    children_by_parent = {
        _suffix(g.root): [g.coder, g.monitor, g.duplicate, g.parallel],
        _suffix(g.coder): [g.monitor],
        _suffix(g.monitor): [g.gate, g.root],
    }

    turns = _descendant_agent_session_turns([g.root], children_by_parent)

    assert _names(turns) == ["alpha--mon", "alpha--gate"]


def test_loaded_tree_rows_list_every_row_once_loaded_before_targets() -> None:
    g = _graph()
    stray = make_agent("stray", role="code")
    stray.runtime_children = [g.parallel]

    rows = _loaded_tree_rows([g.root], [stray, g.coder])

    assert [row.cl_name for row in rows] == [
        "alpha--0",
        "alpha--code",
        "alpha--mon",
        "alpha--gate",
        "alpha--code",
        "alpha--par",
        "stray",
    ]
    assert rows[1] is g.coder and rows[4] is g.duplicate


def test_fold_filter_hides_rows_whose_parent_chain_loops() -> None:
    top = _fold_row("top", suffix="ts-top", parent=None)
    mid = _fold_row("mid", suffix="ts-mid", parent="ts-top")
    leaf = _fold_row("leaf", suffix="ts-leaf", parent="ts-mid")
    loop_a = _fold_row("loop-a", suffix="ts-a", parent="ts-b")
    loop_b = _fold_row("loop-b", suffix="ts-b", parent="ts-a")
    orphan = _fold_row("orphan", suffix="ts-orphan", parent="ts-missing")
    manager = FoldStateManager()
    manager.expand("ts-top")
    manager.expand("ts-mid")

    visible, counts = filter_agents_by_fold_state(
        [top, mid, leaf, loop_a, loop_b, orphan], manager
    )

    assert _names(visible) == ["top", "mid", "leaf"]
    assert counts["ts-top"] == (1, 0)


def test_fold_filter_collapsed_ancestor_hides_the_whole_chain() -> None:
    top = _fold_row("top", suffix="ts-top", parent=None)
    mid = _fold_row("mid", suffix="ts-mid", parent="ts-top")
    leaf = _fold_row("leaf", suffix="ts-leaf", parent="ts-mid")
    manager = FoldStateManager()
    manager.expand("ts-mid")  # mid is expanded, but top is still collapsed

    visible, _ = filter_agents_by_fold_state([top, mid, leaf], manager)

    assert _names(visible) == ["top"]


def test_clan_tree_links_resolve_depth_and_survive_a_parent_loop() -> None:
    first = _clan_row("first", suffix="cs0", parent=None)
    second = _clan_row("second", suffix="cs1", parent="cs0")
    third = _clan_row("third", suffix="cs2", parent="cs1")
    loop_a = _clan_row("loop-a", suffix="cs3", parent="cs4")
    loop_b = _clan_row("loop-b", suffix="cs4", parent="cs3")
    rows = [first, second, third, loop_a, loop_b]

    _assign_clan_tree_links(rows, "clan:x", {_suffix(row): row for row in rows})

    assert [(r.tree_depth, r.tree_parent_key) for r in (first, second, third)] == [
        (1, "clan:x"),
        (2, "cs0"),
        (3, "cs1"),
    ]
    # A loop terminates with every member assigned; the exact values are the
    # long-standing ones the recursive walk produced.
    assert [(r.tree_depth, r.tree_parent_key) for r in (loop_a, loop_b)] == [
        (3, "cs4"),
        (2, "cs3"),
    ]


def test_aggregate_member_collection_is_post_order_and_marks_visited() -> None:
    parent = _plain("parent")
    middle = _plain("middle")
    leaf_one = _plain("leaf-one")
    leaf_two = _plain("leaf-two")
    parent.runtime_children = [middle, leaf_two]
    middle.runtime_children = [leaf_one, leaf_two]
    leaf_one.runtime_children = [middle]  # loop back to a visited row
    seen: set[int] = set()
    visited: list[int] = []

    members = _collect_aggregate_member_rows(parent, False, seen, visited_ids=visited)

    assert _names(members) == ["leaf-one", "leaf-two", "middle"]
    assert visited == [id(middle), id(leaf_one), id(leaf_two)]
    assert seen == set(visited)


def test_row_providers_list_first_launch_order_through_shared_children() -> None:
    parent = _plain("parent", provider="Claude ")
    left = _plain("left", provider="codex", start=3)
    right = _plain("right", provider=None, start=2)
    shared = _plain("shared", provider="claude", start=1)
    parent.runtime_children = [left, right]
    left.runtime_children = [shared]
    right.runtime_children = [shared, parent]  # loop back to an ancestor

    assert ordered_row_providers(parent) == ("claude", "codex")


# --------------------------------------------------------------------------- #
# Zero retained garbage after the result is dropped.
# --------------------------------------------------------------------------- #


def _fold_row(name: str, *, suffix: str, parent: str | None) -> Agent:
    return Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name=name,
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        raw_suffix=suffix,
        parent_workflow="wf" if parent else None,
        parent_timestamp=parent,
        step_name=name if parent else None,
    )


def _clan_row(name: str, *, suffix: str, parent: str | None) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 7, 19, 9, 0, 0),
        raw_suffix=suffix,
        agent_name=f"clanx.{name}",
        agent_clan="clanx",
        agent_clan_generation="1",
        parent_timestamp=parent,
    )


def _plain(name: str, *, provider: str | None = None, start: int = 0) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 7, 19, 9, start, 0),
        raw_suffix=f"suffix-{name}",
        agent_name=name,
        llm_provider=provider,
    )


def _produce_turn_rows() -> None:
    concrete_agent_session_turn_rows(_graph(loop=False).root)


def _produce_sorted_roster() -> None:
    g = _graph(loop=False)
    sort_and_reorder([g.root, g.coder, g.monitor, g.gate], [])


def _produce_source_digest_parts() -> None:
    _source_digest_parts(_graph(loop=False).root)


def _produce_own_turn_walk() -> None:
    _walk_own_turns(_graph(loop=False).root)


def _produce_descendant_rows() -> None:
    _descendant_rows(_graph(loop=False).root)


def _produce_descendant_session_turns() -> None:
    g = _graph(loop=False)
    _descendant_agent_session_turns(
        [g.root], {_suffix(g.root): [g.coder, g.monitor, g.gate]}
    )


def _produce_loaded_tree_rows() -> None:
    g = _graph(loop=False)
    _loaded_tree_rows([g.root], [g.coder])


def _produce_fold_filter() -> None:
    top = _fold_row("top", suffix="ts-top", parent=None)
    mid = _fold_row("mid", suffix="ts-mid", parent="ts-top")
    leaf = _fold_row("leaf", suffix="ts-leaf", parent="ts-mid")
    manager = FoldStateManager()
    manager.expand("ts-top")
    filter_agents_by_fold_state([top, mid, leaf], manager)


def _produce_clan_tree() -> None:
    first = _clan_row("first", suffix="cs0", parent=None)
    second = _clan_row("second", suffix="cs1", parent="cs0")
    project_clan_tree([first, second])


def _produce_aggregate_members() -> None:
    parent = _plain("parent")
    child = _plain("child")
    parent.runtime_children = [child]
    _collect_aggregate_member_rows(parent, False, set())


def _produce_row_providers() -> None:
    parent = _plain("parent", provider="claude")
    child = _plain("child", provider="codex", start=1)
    parent.runtime_children = [child]
    ordered_row_providers(parent)


@dataclass(frozen=True)
class _Producer:
    """One walker exercised through a fresh row graph per call."""

    run: Callable[[], None]
    closure: str
    #: ``False`` when the entry point also installs the model-graph
    #: ``agent_session_container`` backreference, a separate ownership cycle
    #: that is checked for closure scaffolding only.
    rows_freed_by_refcount: bool = True


_PRODUCERS: dict[str, _Producer] = {
    "session-turn-rows": _Producer(
        _produce_turn_rows, "_expand_nested_agent_session_turns"
    ),
    "roster-ordering": _Producer(
        _produce_sorted_roster,
        "_expand_nested_agent_session_turns",
        rows_freed_by_refcount=False,
    ),
    "hint-source-digest": _Producer(
        _produce_source_digest_parts, "_source_digest_parts"
    ),
    "own-turn-walk": _Producer(_produce_own_turn_walk, "_walk_own_turns"),
    "tribe-descendants": _Producer(_produce_descendant_rows, "_descendant_rows"),
    "status-descendant-turns": _Producer(
        _produce_descendant_session_turns, "_descendant_agent_session_turns"
    ),
    "loaded-tree-rows": _Producer(_produce_loaded_tree_rows, "_loaded_tree_rows"),
    "fold-filter": _Producer(_produce_fold_filter, "filter_agents_by_fold_state"),
    "clan-tree-links": _Producer(_produce_clan_tree, "_assign_clan_tree_links"),
    "aggregate-members": _Producer(
        _produce_aggregate_members, "_collect_aggregate_member_rows"
    ),
    "row-providers": _Producer(_produce_row_providers, "ordered_row_providers"),
}


@pytest.mark.parametrize("producer", _PRODUCERS.values(), ids=_PRODUCERS.keys())
def test_walker_releases_rows_and_closures_by_refcount(producer: _Producer) -> None:
    garbage = measure_cycle_garbage(producer.run)

    assert garbage.function_count(producer.closure) == 0, garbage.describe()
    if producer.rows_freed_by_refcount:
        assert garbage.count(AGENT_TYPE) == 0, garbage.describe()
        assert garbage.total == 0, garbage.describe()
