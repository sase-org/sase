"""Tests for jump-to-entry hint assignment and input matching."""

from sase.ace.tui.actions.navigation.jump_hints import (
    JUMP_HINT_CAPACITY,
    JUMP_HINT_CHARS,
    JumpHintMatchOutcome,
    build_jump_hint_maps,
    match_jump_hint,
    normalize_jump_key,
)
from tests.ace.tui._jump_to_entry_hints_helpers import (
    _InlineJumpApp,
    _InlineJumpEventApp,
    _KeyEvent,
    _make_changespec,
)


def test_build_jump_hint_maps_uses_expected_order() -> None:
    indices = [10, 11, 12]
    hint_to_index, index_to_hint = build_jump_hint_maps(indices)
    assert hint_to_index == {"0": 10, "1": 11, "2": 12}
    assert index_to_hint == {10: "0", 11: "1", 12: "2"}


def test_build_jump_hint_maps_uses_one_character_through_exactly_62() -> None:
    indices = list(range(len(JUMP_HINT_CHARS)))
    hint_to_index, index_to_hint = build_jump_hint_maps(indices)
    assert len(hint_to_index) == len(JUMP_HINT_CHARS)
    assert hint_to_index["0"] == 0
    assert hint_to_index["9"] == 9
    assert hint_to_index["a"] == 10
    assert hint_to_index["z"] == 35
    assert hint_to_index["A"] == 36
    assert hint_to_index["Z"] == 61
    assert index_to_hint[61] == "Z"


def test_build_jump_hint_maps_switches_entire_63_target_session_to_two_chars() -> None:
    hint_to_index, index_to_hint = build_jump_hint_maps(list(range(63)))

    assert hint_to_index["00"] == 0
    assert hint_to_index["09"] == 9
    assert hint_to_index["0a"] == 10
    assert hint_to_index["0Z"] == 61
    assert hint_to_index["10"] == 62
    assert index_to_hint[0] == "00"


def test_build_jump_hint_maps_stops_at_zz_capacity() -> None:
    targets = list(range(JUMP_HINT_CAPACITY + 2))
    hint_to_index, index_to_hint = build_jump_hint_maps(targets)

    assert len(hint_to_index) == JUMP_HINT_CAPACITY
    assert hint_to_index["ZZ"] == JUMP_HINT_CAPACITY - 1
    assert JUMP_HINT_CAPACITY not in index_to_hint


def test_build_jump_hint_maps_one_target_starts_at_zero() -> None:
    assert build_jump_hint_maps(["only"]) == ({"0": "only"}, {"only": "0"})


def test_jump_hint_alphabet_has_62_chars() -> None:
    assert len(JUMP_HINT_CHARS) == 62


def test_match_jump_hint_waits_for_two_character_completion() -> None:
    hint_to_target, _ = build_jump_hint_maps(list(range(63)))

    pending = match_jump_hint(hint_to_target, "", "1")
    complete = match_jump_hint(hint_to_target, pending.prefix, "0")

    assert pending.outcome is JumpHintMatchOutcome.PENDING
    assert pending.prefix == "1"
    assert complete.outcome is JumpHintMatchOutcome.COMPLETE
    assert complete.target == 62


def test_match_jump_hint_is_case_sensitive_and_rejects_invalid_sequences() -> None:
    hint_to_target, _ = build_jump_hint_maps(list(range(63)))

    assert match_jump_hint(hint_to_target, "0", "Z").target == 61
    assert (
        match_jump_hint(hint_to_target, "0", "z").outcome
        is JumpHintMatchOutcome.COMPLETE
    )
    assert (
        match_jump_hint(hint_to_target, "Z", "Z").outcome
        is JumpHintMatchOutcome.INVALID
    )


def test_match_jump_hint_keeps_one_character_sessions_immediate() -> None:
    hint_to_target, _ = build_jump_hint_maps([10, 11])

    match = match_jump_hint(hint_to_target, "", "1")

    assert match.outcome is JumpHintMatchOutcome.COMPLETE
    assert match.target == 11


def test_normalize_jump_key_prefers_uppercase_hint_character() -> None:
    assert normalize_jump_key("a", "A") == "A"
    assert normalize_jump_key("apostrophe", "'") == "apostrophe"
    assert normalize_jump_key("grave_accent", "`") == "grave_accent"
    assert normalize_jump_key("escape", None) == "escape"


def test_inline_jump_to_entry_allocates_and_dispatches_uppercase_hint() -> None:
    changespecs = [_make_changespec(f"feature_{i:02d}") for i in range(37)]
    app = _InlineJumpApp(changespecs)

    app.action_jump_to_entry()

    assert app._entry_jump_hint_to_index["A"] == 36
    assert app._entry_jump_index_to_hint[36] == "A"

    handled = app._handle_entry_jump_key("A")

    assert handled is True
    assert app.current_idx == 36
    assert app._entry_jump_mode_active is False


def test_inline_two_character_jump_waits_for_second_character() -> None:
    app = _InlineJumpApp([_make_changespec(f"feature_{i:02d}") for i in range(63)])

    app.action_jump_to_entry()

    assert app._entry_jump_index_to_hint[0] == "00"
    assert app._entry_jump_index_to_hint[62] == "10"
    refreshes_after_activation = app.refreshes
    assert app._handle_entry_jump_key("1") is True
    assert app.current_idx == 0
    assert app._entry_jump_mode_active is True
    assert app._entry_jump_pending_prefix == "1"
    assert app.refreshes == refreshes_after_activation

    assert app._handle_entry_jump_key("0") is True
    assert app.current_idx == 62
    assert app._entry_jump_mode_active is False
    assert app._entry_jump_pending_prefix == ""


def test_inline_two_character_jump_escape_clears_partial_prefix() -> None:
    app = _InlineJumpApp([_make_changespec(f"feature_{i:02d}") for i in range(63)])
    app.action_jump_to_entry()
    assert app._handle_entry_jump_key("0") is True

    assert app._handle_entry_jump_key("escape") is True

    assert app._entry_jump_mode_active is False
    assert app._entry_jump_pending_prefix == ""


def test_inline_jump_on_key_uses_uppercase_event_character() -> None:
    app = _InlineJumpEventApp()
    event = _KeyEvent(key="a", character="A")

    app.on_key(event)  # type: ignore[arg-type]

    assert app.handled_keys == ["A"]
    assert event.prevented is True
    assert event.stopped is True
