"""Tests for the Agents-tab cyclable layouts and panel rotation state."""

from __future__ import annotations

import pytest

from sase.ace.tui.models.agent_panels import (
    AgentsLayout,
    AgentsLayoutState,
    PanelSlot,
)


def test_default_state_is_classic_with_lcf_order() -> None:
    state = AgentsLayoutState()
    assert state.layout is AgentsLayout.CLASSIC
    assert state.order == (PanelSlot.LIST, PanelSlot.CHAT, PanelSlot.FILE)
    assert state.primary is PanelSlot.LIST


def test_cycle_layout_walks_full_cycle_forward_and_wraps() -> None:
    state = AgentsLayoutState()
    expected = [
        AgentsLayout.TRIPTYCH,
        AgentsLayout.STACK,
        AgentsLayout.FOCUS,
        AgentsLayout.CLASSIC,
    ]
    for want in expected:
        assert state.cycle_layout() is want
        assert state.layout is want


def test_cycle_layout_walks_full_cycle_reverse_and_wraps() -> None:
    state = AgentsLayoutState()
    expected = [
        AgentsLayout.FOCUS,
        AgentsLayout.STACK,
        AgentsLayout.TRIPTYCH,
        AgentsLayout.CLASSIC,
    ]
    for want in expected:
        assert state.cycle_layout(reverse=True) is want
        assert state.layout is want


def test_rotate_is_cyclic_shift_returning_home_in_three_steps() -> None:
    state = AgentsLayoutState()
    assert state.rotate() == (PanelSlot.CHAT, PanelSlot.FILE, PanelSlot.LIST)
    assert state.rotate() == (PanelSlot.FILE, PanelSlot.LIST, PanelSlot.CHAT)
    assert state.rotate() == (PanelSlot.LIST, PanelSlot.CHAT, PanelSlot.FILE)


def test_rotate_reverse_cycles_in_opposite_direction() -> None:
    state = AgentsLayoutState()
    assert state.rotate(reverse=True) == (
        PanelSlot.FILE,
        PanelSlot.LIST,
        PanelSlot.CHAT,
    )
    assert state.rotate(reverse=True) == (
        PanelSlot.CHAT,
        PanelSlot.FILE,
        PanelSlot.LIST,
    )
    assert state.rotate(reverse=True) == (
        PanelSlot.LIST,
        PanelSlot.CHAT,
        PanelSlot.FILE,
    )


def test_rotate_forward_then_reverse_is_identity() -> None:
    state = AgentsLayoutState()
    state.rotate()
    state.rotate(reverse=True)
    assert state.order == (PanelSlot.LIST, PanelSlot.CHAT, PanelSlot.FILE)


def test_slot_for_position_returns_correct_slot_after_rotation() -> None:
    state = AgentsLayoutState()
    assert state.slot_for_position(1) is PanelSlot.LIST
    assert state.slot_for_position(2) is PanelSlot.CHAT
    assert state.slot_for_position(3) is PanelSlot.FILE

    state.rotate()  # -> (CHAT, FILE, LIST)
    assert state.slot_for_position(1) is PanelSlot.CHAT
    assert state.slot_for_position(2) is PanelSlot.FILE
    assert state.slot_for_position(3) is PanelSlot.LIST

    state.rotate()  # -> (FILE, LIST, CHAT)
    assert state.slot_for_position(1) is PanelSlot.FILE
    assert state.slot_for_position(2) is PanelSlot.LIST
    assert state.slot_for_position(3) is PanelSlot.CHAT


def test_slot_for_position_rejects_out_of_range() -> None:
    state = AgentsLayoutState()
    with pytest.raises(ValueError):
        state.slot_for_position(0)
    with pytest.raises(ValueError):
        state.slot_for_position(4)


def test_position_for_slot_is_inverse_of_slot_for_position() -> None:
    state = AgentsLayoutState()
    state.rotate()  # (CHAT, FILE, LIST)
    for slot in PanelSlot:
        position = state.position_for_slot(slot)
        assert state.slot_for_position(position) is slot


def test_primary_tracks_rotation_after_layout_changes() -> None:
    """Cycling layouts must NOT affect the panel order — they're orthogonal."""
    state = AgentsLayoutState()
    state.rotate()  # primary becomes CHAT
    assert state.primary is PanelSlot.CHAT
    state.cycle_layout()
    state.cycle_layout()
    assert state.primary is PanelSlot.CHAT
    assert state.order == (PanelSlot.CHAT, PanelSlot.FILE, PanelSlot.LIST)
