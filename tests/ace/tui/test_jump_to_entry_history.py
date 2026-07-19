"""Tests for jump-to-entry navigation history."""

from tests.ace.tui._jump_to_entry_hints_helpers import (
    _InlineJumpApp,
    _make_changespec,
)


def test_apostrophe_selects_first_target_directly_at_two_character_width() -> None:
    app = _InlineJumpApp([_make_changespec(f"feature_{i:02d}") for i in range(63)])
    app.current_idx = 62

    app.action_jump_to_entry()
    assert app._handle_entry_jump_key("apostrophe") is True

    assert app.current_idx == 0
    assert app._entry_jump_index_stack["changespecs"] == [62]


def test_fast_jump_selects_first_target_directly_at_two_character_width() -> None:
    app = _InlineJumpApp([_make_changespec(f"feature_{i:02d}") for i in range(63)])
    app.current_idx = 62

    app.action_jump_to_entry_fast()

    assert app.current_idx == 0
    assert app._entry_jump_index_stack["changespecs"] == [62]
    assert app._entry_jump_pending_prefix == ""


def test_apostrophe_without_history_dispatches_first_changespec_hint() -> None:
    changespecs = [_make_changespec(f"feature_{i:02d}") for i in range(3)]
    app = _InlineJumpApp(changespecs)
    app.current_idx = 2

    app.action_jump_to_entry()
    handled = app._handle_entry_jump_key("apostrophe")

    assert handled is True
    assert app.current_idx == 0
    assert app._entry_jump_index_stack["changespecs"] == [2]
    assert app._entry_jump_mode_active is False


def test_fast_jump_without_history_dispatches_first_changespec_without_footer() -> None:
    changespecs = [_make_changespec(f"feature_{i:02d}") for i in range(3)]
    app = _InlineJumpApp(changespecs)
    app.current_idx = 2

    app.action_jump_to_entry_fast()

    assert app.current_idx == 0
    assert app._entry_jump_index_stack["changespecs"] == [2]
    assert app._entry_jump_mode_active is False
    assert app.jump_footer_updates == 0


def test_fast_jump_with_history_restores_changespec_and_pops_origin() -> None:
    changespecs = [_make_changespec(f"feature_{i:02d}") for i in range(3)]
    app = _InlineJumpApp(changespecs)
    app.current_idx = 2
    app._entry_jump_index_stack["changespecs"] = [1]

    app.action_jump_to_entry_fast()

    assert app.current_idx == 1
    assert app._entry_jump_index_stack["changespecs"] == []
    assert app._entry_jump_mode_active is False
    assert app.jump_footer_updates == 0


def test_changespec_jump_stack_walks_back_and_forward() -> None:
    changespecs = [_make_changespec(f"feature_{i:02d}") for i in range(3)]
    app = _InlineJumpApp(changespecs)
    app.current_idx = 2

    app.action_jump_to_entry()
    handled = app._handle_entry_jump_key("0")

    assert handled is True
    assert app.current_idx == 0
    assert app._entry_jump_index_stack["changespecs"] == [2]

    app.action_jump_to_entry_fast()

    assert app.current_idx == 2
    assert app._entry_jump_index_stack["changespecs"] == []
    assert app._entry_jump_forward_index_stack["changespecs"] == [0]

    app.action_jump_to_entry_forward()

    assert app.current_idx == 0
    assert app._entry_jump_index_stack["changespecs"] == [2]
    assert app._entry_jump_forward_index_stack["changespecs"] == []


def test_new_changespec_hint_jump_clears_forward_history() -> None:
    changespecs = [_make_changespec(f"feature_{i:02d}") for i in range(3)]
    app = _InlineJumpApp(changespecs)
    app.current_idx = 2
    app._entry_jump_forward_index_stack["changespecs"] = [0]

    app.action_jump_to_entry()
    handled = app._handle_entry_jump_key("1")

    assert handled is True
    assert app.current_idx == 1
    assert app._entry_jump_index_stack["changespecs"] == [2]
    assert app._entry_jump_forward_index_stack["changespecs"] == []


def test_push_changespec_to_history_records_origin_and_clears_forward() -> None:
    changespecs = [_make_changespec(f"feature_{i:02d}") for i in range(3)]
    app = _InlineJumpApp(changespecs)
    app.current_idx = 2
    app._entry_jump_forward_index_stack["changespecs"] = [0]

    app._push_changespec_to_history()

    assert app._entry_jump_index_stack["changespecs"] == [2]
    assert app._entry_jump_forward_index_stack["changespecs"] == []


def test_forward_jump_discards_stale_changespec_anchor() -> None:
    changespecs = [_make_changespec(f"feature_{i:02d}") for i in range(2)]
    app = _InlineJumpApp(changespecs)
    app.current_idx = 1
    app._entry_jump_forward_index_stack["changespecs"] = [9]

    app.action_jump_to_entry_forward()

    assert app.current_idx == 1
    assert "changespecs" not in app._entry_jump_forward_index_stack
    app.notify.assert_called_once_with(
        "No next jump point",
        severity="information",
    )


def test_changespec_banner_anchor_restores_forward() -> None:
    changespecs = [
        _make_changespec("a_one", project="alpha"),
        _make_changespec("b_one", project="beta"),
    ]
    app = _InlineJumpApp(changespecs)
    app.current_idx = 1
    app._changespec_group_fold_registry.collapse(("alpha",))

    app.action_jump_to_entry()
    banner_hint = app._entry_jump_changespec_banner_to_hint[("alpha",)]
    handled = app._handle_entry_jump_key(banner_hint)

    assert handled is True
    assert app._current_changespec_group_key == ("alpha",)
    assert app.current_idx == 1
    assert app._entry_jump_index_stack["changespecs"] == [1]

    app.action_jump_to_entry_fast()

    assert app._current_changespec_group_key is None
    assert app.current_idx == 1
    assert app._entry_jump_forward_index_stack["changespecs"] == [
        ("changespec_banner", ("alpha",))
    ]

    app.action_jump_to_entry_forward()

    assert app._current_changespec_group_key == ("alpha",)
    assert app.current_idx == 1
    assert app._entry_jump_index_stack["changespecs"] == [1]


def test_fast_jump_with_history_pops_changespec_stack_lifo() -> None:
    changespecs = [_make_changespec(f"feature_{i:02d}") for i in range(4)]
    app = _InlineJumpApp(changespecs)
    app.current_idx = 3
    app._entry_jump_index_stack["changespecs"] = [0, 1, 2]

    app.action_jump_to_entry_fast()
    assert app.current_idx == 2
    assert app._entry_jump_index_stack["changespecs"] == [0, 1]

    app.action_jump_to_entry_fast()
    assert app.current_idx == 1
    assert app._entry_jump_index_stack["changespecs"] == [0]

    app.action_jump_to_entry_fast()
    assert app.current_idx == 0
    assert app._entry_jump_index_stack["changespecs"] == []


def test_fast_jump_discards_stale_changespec_back_stack_before_fallback() -> None:
    changespecs = [_make_changespec(f"feature_{i:02d}") for i in range(2)]
    app = _InlineJumpApp(changespecs)
    app.current_idx = 1
    app._entry_jump_index_stack["changespecs"] = [9]

    app.action_jump_to_entry_fast()

    assert app.current_idx == 0
    assert app._entry_jump_index_stack["changespecs"] == [1]
    assert app._entry_jump_mode_active is False
    assert app.jump_footer_updates == 0


def test_fast_jump_discards_stale_changespec_back_stack_before_valid_restore() -> None:
    changespecs = [_make_changespec(f"feature_{i:02d}") for i in range(2)]
    app = _InlineJumpApp(changespecs)
    app.current_idx = 1
    app._entry_jump_index_stack["changespecs"] = [0, 9]

    app.action_jump_to_entry_fast()

    assert app.current_idx == 0
    assert app._entry_jump_index_stack["changespecs"] == []
    assert app._entry_jump_mode_active is False
    assert app.jump_footer_updates == 0
