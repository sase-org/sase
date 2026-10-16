"""Rust-backed clan-wave layout and TUI model adaptation tests."""

from __future__ import annotations

from datetime import datetime, timedelta

from sase.ace.tui.models._agent_clan_waves import (
    project_clan_wave_model,
)
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_live_query_engine import apply_agents_live_query_filter

_START = datetime(2026, 10, 15, 12, 0, 0)


def _member(
    clan: str,
    suffix: str,
    index: int,
    *,
    status: str = "WAITING",
    waits: tuple[str, ...] = (),
    wait_beads: tuple[str, ...] = (),
    wait_hoods: tuple[str, ...] = (),
    phase_bead: str | None = None,
    epic_bead: str | None = None,
) -> Agent:
    name = f"{clan}.{suffix}"
    row = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/waves/project.sase",
        status=status,
        start_time=_START + timedelta(seconds=index),
        raw_suffix=f"20261015{index:06d}",
        agent_name=name,
        agent_clan=clan,
        agent_clan_generation="generation-1",
        phase_bead_id=phase_bead,
        epic_bead_id=epic_bead,
    )
    row.waiting_for = list(waits)
    row.waiting_for_beads = list(wait_beads)
    row.waiting_for_hoods = list(wait_hoods)
    return row


def _project(*members: Agent) -> tuple[Agent, ...]:
    return tuple(project_clan_tree(list(members)))


def _container(rows: tuple[Agent, ...]) -> Agent:
    return next(row for row in rows if row.is_clan_container)


def _wave(rows: tuple[Agent, ...], suffix: str) -> int | None:
    member = next(
        row
        for row in rows
        if row.agent_name is not None and row.agent_name.endswith(f".{suffix}")
    )
    assert member.clan_wave_slot is not None
    return member.clan_wave_slot.wave_index


def test_epic_chain_seal_and_same_wave_fanout_use_the_real_binding() -> None:
    members = (
        _member("bob-cli-7v", "1", 1, status="DONE", phase_bead="sase-1"),
        _member("bob-cli-7v", "2", 2, status="RUNNING", phase_bead="sase-2"),
        _member("bob-cli-7v", "3", 3, status="WAITING", phase_bead="sase-3"),
        _member(
            "bob-cli-7v",
            "4",
            4,
            waits=("bob-cli-7v.3",),
            phase_bead="sase-4",
        ),
        _member(
            "bob-cli-7v",
            "5",
            5,
            waits=("bob-cli-7v.4",),
            phase_bead="sase-5",
        ),
        _member(
            "bob-cli-7v",
            "land",
            6,
            waits=("bob-cli-7v.5",),
            epic_bead="sase-epic",
        ),
    )
    rows = _project(*members)
    summary = _container(rows).clan_waves

    assert summary is not None
    assert summary.layered is True
    assert summary.numbered_wave_count == 3
    assert summary.has_seal is True
    assert [_wave(rows, suffix) for suffix in ("1", "2", "3", "4", "5", "land")] == [
        1,
        1,
        1,
        2,
        3,
        None,
    ]
    assert next(
        member
        for member in summary.members
        if member.identity.endswith(":bob-cli-7v.4")
    ).predecessors == (
        next(
            member
            for member in summary.members
            if member.identity.endswith(":bob-cli-7v.3")
        ).identity,
    )
    assert (
        next(
            row
            for row in rows
            if row.agent_name is not None and row.agent_name.endswith(".land")
        ).clan_wave_slot.label_kind
        == "seal"
    )

    swarm = _project(
        _member("research-4j", "linker", 10),
        _member("research-4j", "image", 11, waits=("research-4j.linker",)),
        _member("research-4j", "audio", 12, waits=("research-4j.linker",)),
    )
    assert _wave(swarm, "image") == _wave(swarm, "audio") == 2


def test_long_chain_flat_clan_and_cycle_placements() -> None:
    chain_members = [
        _member(
            "toobig-5y",
            str(index),
            index,
            waits=(f"toobig-5y.{index - 1}",) if index > 1 else (),
        )
        for index in range(1, 15)
    ]
    chain = _project(*chain_members)
    chain_summary = _container(chain).clan_waves
    assert chain_summary is not None
    assert chain_summary.numbered_wave_count == 14
    assert _wave(chain, "1") == 1
    assert _wave(chain, "14") == 14

    flat = _project(
        _member("flat", "a", 1),
        _member("flat", "b", 2),
        _member("flat", "c", 3),
    )
    assert _container(flat).clan_waves is not None
    assert _container(flat).clan_waves.layered is False
    assert {_wave(flat, suffix) for suffix in ("a", "b", "c")} == {1}

    cycle = _project(
        _member("cycle", "a", 1, waits=("cycle.b",)),
        _member("cycle", "b", 2, waits=("cycle.a",)),
    )
    cycle_summary = _container(cycle).clan_waves
    assert cycle_summary is not None
    assert cycle_summary.layered is True
    assert cycle_summary.unresolved_identities
    assert all(
        row.clan_wave_slot.label_kind == "unresolved"
        for row in cycle
        if row.tree_depth == 1
    )


def test_dismissed_ghosts_preserve_wave_numbers_and_live_queries_do_not_reproject() -> (
    None
):
    first = _member("ghost-clan", "first", 1)
    blocker = _member("ghost-clan", "blocker", 2, waits=("ghost-clan.first",))
    target = _member("ghost-clan", "target", 3, waits=("ghost-clan.blocker",))
    complete_rows = _project(first, blocker, target)
    assert _wave(complete_rows, "target") == 3

    # Live queries filter the already-projected member rows, preserving the
    # member's stable slot from the full roster while hiding its blocker.
    member_rows = tuple(row for row in complete_rows if not row.is_clan_container)
    visible, _facade, error = apply_agents_live_query_filter(
        "name:ghost-clan.target",
        member_rows,
    )
    assert error is None
    assert blocker not in visible
    assert _wave(tuple(visible), "target") == 3

    dismissed_rows = _project(target)
    dismissed_summary = _container(dismissed_rows).clan_waves
    assert dismissed_summary is not None
    assert _wave(dismissed_rows, "target") == 2
    ghost_wave = next(wave for wave in dismissed_summary.waves if wave.ghost_names)
    assert ghost_wave.state == "dismissed_only"
    assert ghost_wave.number == 1


def test_owner_prefixed_names_and_hood_waits_resolve_to_the_same_clan() -> None:
    first = _member("raw-clan", "first", 1)
    waiter = _member(
        "raw-clan",
        "waiter",
        2,
        waits=("raw-clan.first",),
        wait_hoods=("raw-clan",),
    )
    for row in (first, waiter):
        row.presented_identity_name = f"fleet-owner/{row.agent_name}"
        row.presented_agent_name = row.presented_identity_name

    rows = _project(first, waiter)
    summary = _container(rows).clan_waves

    assert _container(rows).presented_clan_reference_name() == "fleet-owner/raw-clan"
    assert _wave(rows, "waiter") == 2
    assert summary is not None
    waiter_view = next(
        view for view in summary.members if view.identity.endswith(":raw-clan.waiter")
    )
    assert waiter_view.predecessors


def test_duplicate_presented_names_keep_both_members_and_wait_edges() -> None:
    first = _member("duplicates", "first", 1)
    second = _member("duplicates", "second", 2)
    waiter = _member(
        "duplicates",
        "waiter",
        3,
        waits=("shared-presented-name",),
    )
    for row in (first, second):
        row.presented_identity_name = "shared-presented-name"
        row.presented_agent_name = "shared-presented-name"

    rows = _project(first, second, waiter)
    summary = _container(rows).clan_waves

    assert summary is not None
    assert len(summary.members) == 3
    waiter_view = next(
        view for view in summary.members if view.identity.endswith(".waiter")
    )
    assert len(waiter_view.predecessors) == 2
    assert {identity.rsplit(":", 1)[-1] for identity in waiter_view.predecessors} == {
        "duplicates.first",
        "duplicates.second",
    }
    assert _wave(rows, "waiter") == 2


def test_unit_wait_union_bead_edges_external_counts_and_retry_slot() -> None:
    root = _member("adapter", "root", 1, phase_bead="bead-root")
    child = _member("adapter", "root--plan", 2, waits=("adapter.blocker--plan",))
    child.agent_clan = None
    child.agent_clan_generation = None
    child.parent_timestamp = root.raw_suffix
    blocker = _member("adapter", "blocker", 3, phase_bead="bead-blocker")
    bead_waiter = _member(
        "adapter",
        "bead-waiter",
        4,
        wait_beads=("bead-blocker",),
    )
    bead_waiter.waiting_for = ["outside.agent", "time=10s"]
    retry = _member("adapter", "retry", 5)
    retry.retry_chain_root_timestamp = root.raw_suffix

    projected = _project(root, child, blocker, bead_waiter, retry)
    summary = _container(projected).clan_waves

    assert summary is not None
    assert _wave(projected, "root") == _wave(projected, "retry")
    bead_waiter_view = next(
        view
        for view in summary.members
        if view.identity.endswith(":adapter.bead-waiter")
    )
    assert bead_waiter_view.external_wait_count == 1
    root_view = next(
        view for view in summary.members if view.identity.endswith(":adapter.root")
    )
    assert root_view.predecessors
    assert _wave(projected, "root") > _wave(projected, "blocker")
    assert _wave(projected, "bead-waiter") > _wave(projected, "blocker")


def test_wave_states_fold_current_rows_and_retried_failures_are_handled() -> None:
    cases = (
        ("failed", "FAILED", "failed"),
        ("asking", "QUESTION", "needs_you"),
        ("review", "PLAN", "needs_you"),
        ("running", "RUNNING", "in_flight"),
        ("done", "DONE", "done"),
        ("waiting", "WAITING", "not_started"),
    )
    for clan, status, expected in cases:
        rows = _project(_member(clan, "one", 1, status=status))
        assert _container(rows).clan_waves.waves[0].state == expected

    mixed = _project(
        _member("mixed", "done", 1, status="DONE"),
        _member("mixed", "waiting", 2, status="WAITING"),
    )
    assert _container(mixed).clan_waves.waves[0].state == "in_flight"

    retried = _member("retried", "old", 1, status="FAILED")
    retried.retried_as_timestamp = "20261015000002"
    retried_rows = _project(retried)
    assert _container(retried_rows).clan_waves.waves[0].state == "done"

    dismiss = _project(_member("dismiss", "later", 2, waits=("dismiss.dismissed",)))
    assert any(
        wave.state == "dismissed_only" for wave in _container(dismiss).clan_waves.waves
    )


def test_wave_state_folds_anchors_only_and_done_with_ghost_is_done() -> None:
    anchor = _member("anchors", "member", 1, status="DONE")
    failed_turn = _member("anchors", "member--plan", 2, status="FAILED")
    failed_turn.agent_clan = None
    failed_turn.agent_clan_generation = None
    failed_turn.parent_timestamp = anchor.raw_suffix
    rows = _project(anchor, failed_turn)
    summary = _container(rows).clan_waves
    assert summary is not None
    assert summary.waves[0].state == "done"

    first = _member("ghostdone", "first", 1, status="DONE")
    second = _member(
        "ghostdone",
        "second",
        2,
        status="DONE",
        waits=("ghostdone.first", "ghostdone.dismissed"),
    )
    ghost_rows = _project(first, second)
    ghost_summary = _container(ghost_rows).clan_waves
    assert ghost_summary is not None
    first_wave = next(wave for wave in ghost_summary.waves if wave.number == 1)
    assert first_wave.state == "done"
    assert first_wave.ghost_names


def test_projection_memoizes_layout_but_refolds_state(monkeypatch) -> None:
    from sase.core import agent_clan_waves as facade

    calls = 0

    def binding(_request):
        nonlocal calls
        calls += 1
        key = _request["members"][0]["key"]
        return {
            "layered": False,
            "numbered_wave_count": 1,
            "has_seal": False,
            "waves": [
                {
                    "index": 1,
                    "number": 1,
                    "seal": False,
                    "member_keys": [key],
                    "ghost_names": [],
                }
            ],
            "members": [
                {
                    "key": key,
                    "wave_index": 1,
                    "rank": 0,
                    "predecessor_keys": [],
                    "ghost_predecessors": [],
                    "external_wait_count": 0,
                }
            ],
            "unresolved": [],
        }

    monkeypatch.setattr(facade, "require_rust_binding", lambda _name: binding)
    facade.project_clan_waves.cache_clear()
    row = _member("cache", "one", 1, status="RUNNING")
    unit = [row]
    try:
        first, _ = project_clan_wave_model("cache", [unit])
        row.status = "DONE"
        second, _ = project_clan_wave_model("cache", [unit])
        assert calls == 1
        assert first.waves[0].state == "in_flight"
        assert second.waves[0].state == "done"
    finally:
        facade.project_clan_waves.cache_clear()


def test_tree_projection_clears_wave_fields_after_clan_membership_is_removed() -> None:
    member = _member("reset", "one", 1)
    projected = _project(member)
    container = _container(projected)
    assert container.clan_waves is not None
    assert member.clan_wave_slot is not None

    member.agent_clan = None
    member.agent_clan_generation = None
    project_clan_tree([member])

    assert member.clan_waves is None
    assert member.clan_wave_slot is None
