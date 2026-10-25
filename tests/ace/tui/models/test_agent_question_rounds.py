"""Scoping tests for the questions summary lane (phase `lane`).

Reproduces the on-disk parentage of session ``bob-cli-1n.1``: ``--gate``
has parent ``--plan``, ``--gate-0`` has parent ``--1``, and ``--gate-1``
has parent ``--2``. Covers all three selection kinds (container, asking
turn, gate row), dedupe by gate id, causal order, numbering offsets, and
the zero-I/O stubs.
"""

from __future__ import annotations

from sase.ace.tui.models.agent_question_rounds import (
    QuestionRoundStub,
    question_member_label,
    question_round_stubs,
    question_rows_in_scope,
    questions_cache_key,
    session_question_gate_rows,
)
from tests.ace.tui.models._agent_session_members_helpers import (
    make_agent,
    make_gate_member,
)

__all__ = [
    "test_asking_turn_sees_only_its_own_round",
    "test_container_sees_every_round_in_causal_order",
    "test_dedupe_by_gate_id_keeps_causal_order",
    "test_gate_row_sees_itself",
    "test_non_question_gates_are_out_of_scope",
    "test_numbering_offsets_are_session_wide",
    "test_scope_caps_at_fifty_newest",
    "test_stubs_carry_first_paint_fields",
]


def _question_session() -> tuple[
    object, object, object, object, object, object, object
]:
    """Build container + three asking turns + one question gate each."""
    root = make_agent("alpha--0", role="root")
    plan = make_agent("alpha--plan", role="plan", parent_timestamp=root.raw_suffix)
    first = make_agent("alpha--1", role="1", parent_timestamp=root.raw_suffix)
    second = make_agent("alpha--2", role="2", parent_timestamp=root.raw_suffix)
    root.followup_agents = [plan, first, second]

    gate = make_gate_member(
        "alpha--gate", root=plan, gate_id="g0", gate_state="answered"
    )
    gate.gate_kind = "question"
    gate.gate_creator_agent = "alpha--plan"
    plan.runtime_children = [gate]

    gate0 = make_gate_member(
        "alpha--gate-0", root=first, gate_id="g1", gate_state="pending"
    )
    gate0.gate_kind = "question"
    gate0.gate_creator_agent = "alpha--1"
    gate0.role_suffix = "--gate-0"
    first.runtime_children = [gate0]

    gate1 = make_gate_member(
        "alpha--gate-1", root=second, gate_id="g2", gate_state="timeout"
    )
    gate1.gate_kind = "question"
    gate1.gate_creator_agent = "alpha--2"
    gate1.role_suffix = "--gate-1"
    second.runtime_children = [gate1]

    for member in (plan, first, second, gate, gate0, gate1):
        member.agent_session_container = root

    assert root.is_agent_session_container_row
    return root, plan, first, second, gate, gate0, gate1


def test_container_sees_every_round_in_causal_order() -> None:
    root, _plan, _first, _second, gate, gate0, gate1 = _question_session()

    assert session_question_gate_rows(root) == (gate, gate0, gate1)
    assert question_rows_in_scope(root) == (gate, gate0, gate1)


def test_asking_turn_sees_only_its_own_round() -> None:
    root, plan, first, _second, gate, gate0, gate1 = _question_session()

    assert question_rows_in_scope(plan) == (gate,)
    assert question_rows_in_scope(first) == (gate0,)
    # The container resolution is shared: scope still follows causal order.
    assert session_question_gate_rows(first) == (gate, gate0, gate1)


def test_gate_row_sees_itself() -> None:
    _root, _plan, _first, _second, _gate, gate0, _gate1 = _question_session()

    assert question_rows_in_scope(gate0) == (gate0,)


def test_non_question_gates_are_out_of_scope() -> None:
    root, plan, _first, _second, gate, gate0, gate1 = _question_session()
    other = make_gate_member(
        "alpha--gate-9", root=plan, gate_id="g9", gate_state="answered"
    )
    other.gate_kind = "user"
    other.gate_creator_agent = "alpha--plan"
    plan.runtime_children = [*plan.runtime_children, other]

    assert session_question_gate_rows(root) == (
        gate,
        gate0,
        gate1,
    )
    assert other not in session_question_gate_rows(root)
    assert question_rows_in_scope(other) == ()


def test_dedupe_by_gate_id_keeps_causal_order() -> None:
    root, _plan, _first, second, gate, gate0, gate1 = _question_session()
    duplicate = make_gate_member(
        "alpha--gate-dup", root=second, gate_id="g1", gate_state="answered"
    )
    duplicate.gate_kind = "question"
    duplicate.gate_creator_agent = "alpha--2"
    duplicate.agent_session_container = root
    second.runtime_children = [*second.runtime_children, duplicate]

    # The duplicate gate id collapses onto the first occurrence.
    assert session_question_gate_rows(root) == (gate, gate0, gate1)


def test_scope_caps_at_fifty_newest() -> None:
    root = make_agent("alpha--0", role="root")
    turn = make_agent("alpha--1", role="1", parent_timestamp=root.raw_suffix)
    root.followup_agents = [turn]
    gates = []
    for index in range(60):
        gate = make_gate_member(
            f"alpha--gate-{index}",
            root=turn,
            gate_id=f"g{index}",
            gate_state="answered",
        )
        gate.gate_kind = "question"
        gate.gate_creator_agent = "alpha--1"
        gates.append(gate)
    turn.runtime_children = list(gates)

    rows = session_question_gate_rows(root)
    assert len(rows) == 50
    assert rows[0].gate_id == "g10"
    assert rows[-1].gate_id == "g59"


def test_stubs_carry_first_paint_fields() -> None:
    root, _plan, first, _second, _gate, gate0, _gate1 = _question_session()

    (stub,) = question_round_stubs(first)
    assert isinstance(stub, QuestionRoundStub)
    assert stub.gate_id == "g1"
    assert stub.member_label == "gate-0"
    assert stub.gate_state == "pending"
    assert stub.gate_label == "alpha--gate-0"
    assert stub.asked_at_unix is not None
    assert stub.deadline_unix is None

    (container_stub,) = question_round_stubs(root)[:1]
    assert question_member_label(_gate) == "gate"

    assert container_stub.member_label == "gate"


def test_numbering_offsets_are_session_wide() -> None:
    root, _plan, first, _second, _gate, _gate0, _gate1 = _question_session()

    # Session-wide numbering counts every session row's entries, even rows
    # out of scope: the resolver test pins the offsets, here the scope
    # helpers pin the shared inputs (causal order + per-row entry counts
    # come from the loaded views).
    assert [row.gate_id for row in session_question_gate_rows(root)] == [
        "g0",
        "g1",
        "g2",
    ]
    assert [row.gate_id for row in question_rows_in_scope(first)] == ["g1"]
    assert questions_cache_key(root) == (
        ("g0", "answered"),
        ("g1", "pending"),
        ("g2", "timeout"),
    )
