"""Tests for jump-to-entry navigation history."""

from tests.ace.tui._jump_to_entry_hints_helpers import (
    _InlineJumpApp,
    _make_patch,
)


def test_apostrophe_selects_first_target_directly_at_two_character_width() -> None:
    app = _InlineJumpApp([_make_patch(f"feature_{i:02d}") for i in range(63)])
    app.current_idx = 62

    app.action_jump_to_entry()
    assert app._handle_entry_jump_key("apostrophe") is True

    assert app.current_idx == 0
    assert app._entry_jump_index_stack["patches"] == [62]


def test_fast_jump_selects_first_target_directly_at_two_character_width() -> None:
    app = _InlineJumpApp([_make_patch(f"feature_{i:02d}") for i in range(63)])
    app.current_idx = 62

    app.action_jump_to_entry_fast()

    assert app.current_idx == 0
    assert app._entry_jump_index_stack["patches"] == [62]
    assert app._entry_jump_pending_prefix == ""


def test_apostrophe_without_history_dispatches_first_patch_hint() -> None:
    patches = [_make_patch(f"feature_{i:02d}") for i in range(3)]
    app = _InlineJumpApp(patches)
    app.current_idx = 2

    app.action_jump_to_entry()
    handled = app._handle_entry_jump_key("apostrophe")

    assert handled is True
    assert app.current_idx == 0
    assert app._entry_jump_index_stack["patches"] == [2]
    assert app._entry_jump_mode_active is False


def test_fast_jump_without_history_dispatches_first_patch_without_footer() -> None:
    patches = [_make_patch(f"feature_{i:02d}") for i in range(3)]
    app = _InlineJumpApp(patches)
    app.current_idx = 2

    app.action_jump_to_entry_fast()

    assert app.current_idx == 0
    assert app._entry_jump_index_stack["patches"] == [2]
    assert app._entry_jump_mode_active is False
    assert app.jump_footer_updates == 0


def test_fast_jump_with_history_restores_patch_and_pops_origin() -> None:
    patches = [_make_patch(f"feature_{i:02d}") for i in range(3)]
    app = _InlineJumpApp(patches)
    app.current_idx = 2
    app._entry_jump_index_stack["patches"] = [1]

    app.action_jump_to_entry_fast()

    assert app.current_idx == 1
    assert app._entry_jump_index_stack["patches"] == []
    assert app._entry_jump_mode_active is False
    assert app.jump_footer_updates == 0


def test_patch_jump_stack_walks_back_and_forward() -> None:
    patches = [_make_patch(f"feature_{i:02d}") for i in range(3)]
    app = _InlineJumpApp(patches)
    app.current_idx = 2

    app.action_jump_to_entry()
    handled = app._handle_entry_jump_key("0")

    assert handled is True
    assert app.current_idx == 0
    assert app._entry_jump_index_stack["patches"] == [2]

    app.action_jump_to_entry_fast()

    assert app.current_idx == 2
    assert app._entry_jump_index_stack["patches"] == []
    assert app._entry_jump_forward_index_stack["patches"] == [0]

    app.action_jump_to_entry_forward()

    assert app.current_idx == 0
    assert app._entry_jump_index_stack["patches"] == [2]
    assert app._entry_jump_forward_index_stack["patches"] == []


def test_new_patch_hint_jump_clears_forward_history() -> None:
    patches = [_make_patch(f"feature_{i:02d}") for i in range(3)]
    app = _InlineJumpApp(patches)
    app.current_idx = 2
    app._entry_jump_forward_index_stack["patches"] = [0]

    app.action_jump_to_entry()
    handled = app._handle_entry_jump_key("1")

    assert handled is True
    assert app.current_idx == 1
    assert app._entry_jump_index_stack["patches"] == [2]
    assert app._entry_jump_forward_index_stack["patches"] == []


def test_push_patch_to_history_records_origin_and_clears_forward() -> None:
    patches = [_make_patch(f"feature_{i:02d}") for i in range(3)]
    app = _InlineJumpApp(patches)
    app.current_idx = 2
    app._entry_jump_forward_index_stack["patches"] = [0]

    app._push_patch_to_history()

    assert app._entry_jump_index_stack["patches"] == [2]
    assert app._entry_jump_forward_index_stack["patches"] == []


def test_forward_jump_discards_stale_patch_anchor() -> None:
    patches = [_make_patch(f"feature_{i:02d}") for i in range(2)]
    app = _InlineJumpApp(patches)
    app.current_idx = 1
    app._entry_jump_forward_index_stack["patches"] = [9]

    app.action_jump_to_entry_forward()

    assert app.current_idx == 1
    assert "patches" not in app._entry_jump_forward_index_stack
    app.notify.assert_called_once_with(
        "No next jump point",
        severity="information",
    )


def test_patch_banner_anchor_restores_forward() -> None:
    patches = [
        _make_patch("a_one", project="alpha"),
        _make_patch("b_one", project="beta"),
    ]
    app = _InlineJumpApp(patches)
    app.current_idx = 1
    app._patch_group_fold_registry.collapse(("alpha",))

    app.action_jump_to_entry()
    banner_hint = app._entry_jump_patch_banner_to_hint[("alpha",)]
    handled = app._handle_entry_jump_key(banner_hint)

    assert handled is True
    assert app._current_patch_group_key == ("alpha",)
    assert app.current_idx == 1
    assert app._entry_jump_index_stack["patches"] == [1]

    app.action_jump_to_entry_fast()

    assert app._current_patch_group_key is None
    assert app.current_idx == 1
    assert app._entry_jump_forward_index_stack["patches"] == [
        ("patch_banner", ("alpha",))
    ]

    app.action_jump_to_entry_forward()

    assert app._current_patch_group_key == ("alpha",)
    assert app.current_idx == 1
    assert app._entry_jump_index_stack["patches"] == [1]


def test_fast_jump_with_history_pops_patch_stack_lifo() -> None:
    patches = [_make_patch(f"feature_{i:02d}") for i in range(4)]
    app = _InlineJumpApp(patches)
    app.current_idx = 3
    app._entry_jump_index_stack["patches"] = [0, 1, 2]

    app.action_jump_to_entry_fast()
    assert app.current_idx == 2
    assert app._entry_jump_index_stack["patches"] == [0, 1]

    app.action_jump_to_entry_fast()
    assert app.current_idx == 1
    assert app._entry_jump_index_stack["patches"] == [0]

    app.action_jump_to_entry_fast()
    assert app.current_idx == 0
    assert app._entry_jump_index_stack["patches"] == []


def test_fast_jump_discards_stale_patch_back_stack_before_fallback() -> None:
    patches = [_make_patch(f"feature_{i:02d}") for i in range(2)]
    app = _InlineJumpApp(patches)
    app.current_idx = 1
    app._entry_jump_index_stack["patches"] = [9]

    app.action_jump_to_entry_fast()

    assert app.current_idx == 0
    assert app._entry_jump_index_stack["patches"] == [1]
    assert app._entry_jump_mode_active is False
    assert app.jump_footer_updates == 0


def test_fast_jump_discards_stale_patch_back_stack_before_valid_restore() -> None:
    patches = [_make_patch(f"feature_{i:02d}") for i in range(2)]
    app = _InlineJumpApp(patches)
    app.current_idx = 1
    app._entry_jump_index_stack["patches"] = [0, 9]

    app.action_jump_to_entry_fast()

    assert app.current_idx == 0
    assert app._entry_jump_index_stack["patches"] == []
    assert app._entry_jump_mode_active is False
    assert app.jump_footer_updates == 0
