"""Unit tests for the shared Admin Center pane entry-jump mixin."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.modals.pane_entry_jump import (
    JUMP_BACK_STACK_LIMIT,
    PaneEntryJumpMixin,
    apply_jump_hint_prefix,
)


class _FakePane(PaneEntryJumpMixin):
    """Minimal host that records selections and repaints."""

    def __init__(self, target_count: int, *, current: int | None = 0) -> None:
        self.target_count = target_count
        self.current = current
        self.repaints = 0
        self.selected: list[int] = []

    def _jump_target_count(self) -> int:
        return self.target_count

    def _jump_current_index(self) -> int | None:
        return self.current

    def _jump_select_index(self, index: int) -> None:
        self.selected.append(index)
        self.current = index
        self.repaints += 1

    def _jump_repaint(self) -> None:
        self.repaints += 1


def _enter(pane: _FakePane) -> None:
    pane.action_jump_to_entry()


def test_single_character_hints_up_to_sixty_two_targets() -> None:
    pane = _FakePane(62)
    _enter(pane)

    assert pane.jump_mode_active is True
    assert pane.jump_hint_for(0) == "0"
    assert pane.jump_hint_for(10) == "a"
    assert pane.jump_hint_for(61) == "Z"


def test_two_character_hints_beyond_sixty_two_targets() -> None:
    pane = _FakePane(63)
    _enter(pane)

    assert pane.jump_hint_for(0) == "00"
    assert pane.jump_hint_for(62) == "10"


def test_hint_for_returns_none_outside_jump_mode() -> None:
    pane = _FakePane(3)

    assert pane.jump_hint_for(0) is None

    _enter(pane)
    assert pane.jump_hint_for(0) == "0"

    pane.exit_jump_mode()
    assert pane.jump_hint_for(0) is None


def test_zero_targets_is_a_silent_no_op() -> None:
    pane = _FakePane(0)
    _enter(pane)

    assert pane.jump_mode_active is False
    assert pane.repaints == 0
    assert pane.handle_jump_key("0") is False


def test_pending_prefix_completes_a_two_character_hint() -> None:
    pane = _FakePane(70)
    _enter(pane)

    assert pane.handle_jump_key("1") is True
    assert pane.jump_mode_active is True
    assert pane.selected == []

    assert pane.handle_jump_key("2") is True
    assert pane.selected == [64]
    assert pane.jump_mode_active is False


def test_invalid_key_exits_jump_mode_without_selecting() -> None:
    pane = _FakePane(3)
    _enter(pane)

    assert pane.handle_jump_key("z") is True
    assert pane.jump_mode_active is False
    assert pane.selected == []


def test_escape_exits_jump_mode_without_selecting() -> None:
    pane = _FakePane(3)
    _enter(pane)

    assert pane.handle_jump_key("escape") is True
    assert pane.jump_mode_active is False
    assert pane.selected == []


def test_apostrophe_without_history_jumps_to_first_target() -> None:
    pane = _FakePane(3, current=2)
    _enter(pane)

    assert pane.handle_jump_key("apostrophe") is True
    assert pane.selected == [0]
    assert pane.jump_back_stack == [2]


def test_apostrophe_with_history_pops_the_back_stack_without_pushing() -> None:
    pane = _FakePane(3, current=0)
    _enter(pane)
    pane.handle_jump_key("2")
    assert pane.jump_back_stack == [0]

    _enter(pane)
    pane.handle_jump_key("apostrophe")

    assert pane.selected == [2, 0]
    assert pane.jump_back_stack == []


def test_apostrophe_skips_back_stack_entries_outside_the_row_range() -> None:
    pane = _FakePane(5, current=0)
    _enter(pane)
    pane.handle_jump_key("4")
    _enter(pane)
    pane.handle_jump_key("1")
    assert pane.jump_back_stack == [0, 4]

    pane.target_count = 2
    _enter(pane)
    pane.handle_jump_key("apostrophe")

    assert pane.selected == [4, 1, 0]
    assert pane.jump_back_stack == []


def test_no_back_stack_push_when_the_index_does_not_change() -> None:
    pane = _FakePane(3, current=1)
    _enter(pane)

    pane.handle_jump_key("1")

    assert pane.selected == [1]
    assert pane.jump_back_stack == []


def test_back_stack_is_capped_and_drops_the_oldest_entry() -> None:
    pane = _FakePane(2, current=0)
    for _ in range(JUMP_BACK_STACK_LIMIT + 3):
        _enter(pane)
        pane.handle_jump_key("1" if pane.current == 0 else "0")

    assert len(pane.jump_back_stack) == JUMP_BACK_STACK_LIMIT
    assert pane.jump_back_stack[0] == 1


def test_changed_identities_clear_hints_and_the_back_stack() -> None:
    pane = _FakePane(3, current=0)
    _enter(pane)
    pane.handle_jump_key("2")
    assert pane.jump_back_stack == [0]

    _enter(pane)
    pane.invalidate_jump_hints(identities_changed=True, target_count=3)

    assert pane.jump_mode_active is False
    assert pane.jump_back_stack == []


def test_unchanged_identities_clear_only_out_of_range_hints() -> None:
    pane = _FakePane(3, current=0)
    _enter(pane)
    pane.handle_jump_key("2")
    _enter(pane)

    pane.invalidate_jump_hints(identities_changed=False, target_count=3)
    assert pane.jump_mode_active is True
    assert pane.jump_back_stack == [0]

    pane.invalidate_jump_hints(identities_changed=False, target_count=2)
    assert pane.jump_mode_active is False
    assert pane.jump_back_stack == [0]


def test_clear_jump_hints_does_not_repaint() -> None:
    pane = _FakePane(3)
    _enter(pane)
    repaints = pane.repaints

    pane.clear_jump_hints()

    assert pane.jump_mode_active is False
    assert pane.repaints == repaints


def test_jump_state_is_per_instance() -> None:
    first = _FakePane(3)
    second = _FakePane(3)
    _enter(first)

    assert first.jump_mode_active is True
    assert second.jump_mode_active is False
    assert second.jump_hint_for(0) is None


def test_apply_jump_hint_prefix_is_re_exported() -> None:
    decorated = apply_jump_hint_prefix(Text("Sources"), "0")

    assert decorated.plain == "[0] Sources"
