"""Tests for the typed wait-target facade."""

from __future__ import annotations

import pytest

from sase.core import wait_target_facade as facade


def test_parse_wait_target_round_trips_through_real_binding() -> None:
    assert facade.parse_wait_target("session") == "session"
    assert facade.parse_wait_target("turn") == "turn"
    with pytest.raises(RuntimeError, match="did you mean `session`"):
        facade.parse_wait_target("Session")


def test_effective_wait_target_table_cells_through_real_binding() -> None:
    omitted = facade.effective_wait_target(
        requested=None, kind="bare_agent", reference="16h"
    )
    assert omitted == facade.EffectiveWaitTarget(
        target="session", explicit=False, scope="session"
    )

    turn = facade.effective_wait_target(
        requested="turn", kind="bare_agent", reference="16h"
    )
    assert turn == facade.EffectiveWaitTarget(
        target="turn", explicit=True, scope="current_turn"
    )

    member = facade.effective_wait_target(
        requested=None, kind="exact_member", reference="16h--plan"
    )
    assert member == facade.EffectiveWaitTarget(
        target="turn", explicit=False, scope="member"
    )

    proc = facade.effective_wait_target(
        requested="turn", kind="proc", reference="monitor"
    )
    assert proc == facade.EffectiveWaitTarget(
        target="turn", explicit=True, scope="single"
    )


def test_effective_wait_target_errors_name_the_reference() -> None:
    with pytest.raises(RuntimeError, match="`builders`"):
        facade.effective_wait_target(
            requested="turn", kind="clan", reference="builders"
        )
    with pytest.raises(RuntimeError, match="`@job`"):
        facade.effective_wait_target(requested="turn", kind="tribe", reference="@job")
    with pytest.raises(RuntimeError, match="`missing`"):
        facade.effective_wait_target(
            requested="turn", kind="unresolved", reference="missing"
        )


def test_select_current_wait_turn_covers_selection_edges() -> None:
    pending_gate = facade.select_current_wait_turn(
        [
            facade.WaitTurnFacts("t1", pending=False),
            facade.WaitTurnFacts("t3", pending=True),
            facade.WaitTurnFacts("t2", pending=True),
        ]
    )
    assert pending_gate == 1

    all_finished = facade.select_current_wait_turn(
        [
            facade.WaitTurnFacts("t1"),
            facade.WaitTurnFacts("t3"),
            facade.WaitTurnFacts("t2"),
        ]
    )
    assert all_finished == 1

    excluded_waiter = facade.select_current_wait_turn(
        [
            facade.WaitTurnFacts("t1", pending=True),
            facade.WaitTurnFacts("t3", pending=True, excluded=True),
            facade.WaitTurnFacts("t2"),
        ]
    )
    assert excluded_waiter == 0

    parked_sibling = facade.select_current_wait_turn(
        [
            facade.WaitTurnFacts("t1"),
            facade.WaitTurnFacts("t3", pending=True, excluded=True),
            facade.WaitTurnFacts("t2", pending=True),
        ]
    )
    assert parked_sibling == 2

    assert facade.select_current_wait_turn([]) is None
    assert (
        facade.select_current_wait_turn(
            [facade.WaitTurnFacts("t1", pending=True, excluded=True)]
        )
        is None
    )
