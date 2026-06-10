"""Model picker, modal pilot flows, and duration picker coverage."""

from __future__ import annotations

from textual.widgets import Input, Label, OptionList

from sase.ace.tui.modals.model_picker_modal import (
    CUSTOM_SENTINEL,
    ModelPickerModal,
    _build_model_options,
)
from sase.ace.tui.modals.temporary_llm_override_modal import (
    TemporaryLLMOverrideModal,
    TemporaryOverrideResult,
    _DurationPickerModal,
)
from sase.llm_provider.temporary_override import (
    get_active_temporary_override,
    set_temporary_override,
)

from tests._temporary_llm_override_helpers import TemporaryOverrideTestApp


def test_override_modal_picker_options_omit_same_as_planner() -> None:
    """The override flow does not include the Same as planner option id."""
    items = _build_model_options(include_default_option=False)
    ids = {opt.id for opt in items if opt is not None}
    assert "__default__" not in ids
    assert CUSTOM_SENTINEL in ids


def test_override_modal_picker_options_include_known_models() -> None:
    """Even without the default option, common models are still listed."""
    items = _build_model_options(include_default_option=False)
    ids = {opt.id for opt in items if opt is not None}
    assert "opus" in ids
    assert "o3" in ids


async def test_top_modal_q_cancels_when_inactive() -> None:
    """Pressing ``q`` from the inactive state dismisses with cancelled."""
    result: TemporaryOverrideResult | None = None

    async with TemporaryOverrideTestApp().run_test() as pilot:

        def on_dismiss(value: TemporaryOverrideResult | None) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(TemporaryLLMOverrideModal(), callback=on_dismiss)
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()

    assert result is not None
    assert result.action == "cancelled"


async def test_top_modal_x_with_no_active_dismisses_cancelled() -> None:
    """Pressing ``x`` with no active override is a no-op."""
    assert get_active_temporary_override() is None
    result: TemporaryOverrideResult | None = None

    async with TemporaryOverrideTestApp().run_test() as pilot:

        def on_dismiss(value: TemporaryOverrideResult | None) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(TemporaryLLMOverrideModal(), callback=on_dismiss)
        await pilot.pause()
        await pilot.press("x")
        await pilot.pause()

    assert result is not None
    assert result.action == "cancelled"
    assert get_active_temporary_override() is None


async def test_top_modal_s_pushes_model_picker_when_inactive() -> None:
    """Pressing ``s`` from the inactive state pushes the primary picker."""
    async with TemporaryOverrideTestApp().run_test() as pilot:
        modal = TemporaryLLMOverrideModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("s")
        await pilot.pause()

        top = pilot.app.screen
        assert isinstance(top, ModelPickerModal)
        assert top._include_default_option is False
        assert top._title == "Pick Primary Model"


async def test_top_modal_c_pushes_model_picker_when_active() -> None:
    """Pressing ``c`` from the active state pushes the model picker."""
    set_temporary_override("codex/o3", 3600.0, source="test")
    async with TemporaryOverrideTestApp().run_test() as pilot:
        modal = TemporaryLLMOverrideModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("c")
        await pilot.pause()

        top = pilot.app.screen
        assert isinstance(top, ModelPickerModal)
        assert top._title == "Pick Primary Model"


async def test_full_set_flow_writes_state_and_dismisses_with_set() -> None:
    """Set primary override through picker and duration modals."""
    assert get_active_temporary_override() is None
    result: TemporaryOverrideResult | None = None

    async with TemporaryOverrideTestApp().run_test() as pilot:

        def on_dismiss(value: TemporaryOverrideResult | None) -> None:
            nonlocal result
            result = value

        modal = TemporaryLLMOverrideModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("s")
        await pilot.pause()

        picker = pilot.app.screen
        assert isinstance(picker, ModelPickerModal)
        option_list = picker.query_one("#model-picker-list", OptionList)
        option_list.highlighted = option_list.get_option_index("o3")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(pilot.app.screen, _DurationPickerModal)
        await pilot.press("3")
        await pilot.pause()

    assert result is not None
    assert result.action == "set"
    assert result.role == "primary"
    assert result.override is not None
    assert result.override.provider == "codex"
    assert result.override.model == "o3"

    fetched = get_active_temporary_override()
    assert fetched is not None
    assert fetched.provider == "codex"
    assert fetched.model == "o3"
    assert fetched.expires_at is not None


async def test_full_change_flow_overwrites_existing_state() -> None:
    """When an override is active, the change flow replaces it."""
    set_temporary_override("opus", 60.0, source="seed")
    result: TemporaryOverrideResult | None = None

    async with TemporaryOverrideTestApp().run_test() as pilot:

        def on_dismiss(value: TemporaryOverrideResult | None) -> None:
            nonlocal result
            result = value

        modal = TemporaryLLMOverrideModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("c")
        await pilot.pause()

        picker = pilot.app.screen
        assert isinstance(picker, ModelPickerModal)
        option_list = picker.query_one("#model-picker-list", OptionList)
        option_list.highlighted = option_list.get_option_index("o3")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        await pilot.press("6")
        await pilot.pause()

    assert result is not None
    assert result.action == "set"
    assert result.role == "primary"
    fetched = get_active_temporary_override()
    assert fetched is not None
    assert fetched.provider == "codex"
    assert fetched.model == "o3"
    assert fetched.expires_at is None


async def test_top_modal_w_pushes_worker_model_picker() -> None:
    """Pressing ``w`` opens the worker-lane picker."""
    async with TemporaryOverrideTestApp().run_test() as pilot:
        modal = TemporaryLLMOverrideModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("w")
        await pilot.pause()

        top = pilot.app.screen
        assert isinstance(top, ModelPickerModal)
        assert top._include_default_option is False
        assert top._title == "Pick Worker Model"


async def test_full_worker_set_flow_writes_worker_state_only() -> None:
    """The worker flow writes worker state and leaves primary untouched."""
    assert get_active_temporary_override() is None
    assert get_active_temporary_override(role="worker") is None
    result: TemporaryOverrideResult | None = None

    async with TemporaryOverrideTestApp().run_test() as pilot:

        def on_dismiss(value: TemporaryOverrideResult | None) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(TemporaryLLMOverrideModal(), callback=on_dismiss)
        await pilot.pause()

        await pilot.press("w")
        await pilot.pause()

        picker = pilot.app.screen
        assert isinstance(picker, ModelPickerModal)
        option_list = picker.query_one("#model-picker-list", OptionList)
        option_list.highlighted = option_list.get_option_index("o3")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(pilot.app.screen, _DurationPickerModal)
        await pilot.press("3")
        await pilot.pause()

    assert result is not None
    assert result.action == "set"
    assert result.role == "worker"
    assert result.override is not None
    assert result.override.provider == "codex"
    assert result.override.model == "o3"

    assert get_active_temporary_override() is None
    fetched = get_active_temporary_override(role="worker")
    assert fetched is not None
    assert fetched.provider == "codex"
    assert fetched.model == "o3"


async def test_worker_clear_flow_removes_worker_state_only() -> None:
    """``W`` clears the worker override without touching primary state."""
    set_temporary_override("claude/opus", 3600.0, source="seed")
    set_temporary_override("codex/o3", 3600.0, source="seed", role="worker")
    result: TemporaryOverrideResult | None = None

    async with TemporaryOverrideTestApp().run_test() as pilot:

        def on_dismiss(value: TemporaryOverrideResult | None) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(TemporaryLLMOverrideModal(), callback=on_dismiss)
        await pilot.pause()
        await pilot.press("W")
        await pilot.pause()

    assert result is not None
    assert result.action == "cleared"
    assert result.role == "worker"
    assert get_active_temporary_override(role="worker") is None

    primary = get_active_temporary_override()
    assert primary is not None
    assert primary.provider == "claude"
    assert primary.model == "opus"


async def test_set_flow_picker_cancel_keeps_modal_open() -> None:
    """Cancelling the model picker leaves the override modal open."""
    async with TemporaryOverrideTestApp().run_test() as pilot:
        modal = TemporaryLLMOverrideModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("s")
        await pilot.pause()
        assert isinstance(pilot.app.screen, ModelPickerModal)

        await pilot.press("escape")
        await pilot.pause()

        assert isinstance(pilot.app.screen, TemporaryLLMOverrideModal)
        assert get_active_temporary_override() is None

        await pilot.press("escape")
        await pilot.pause()


async def test_duration_modal_invalid_custom_shows_error_keeps_open() -> None:
    """An invalid custom duration shows an error and does not dismiss."""
    dismissed: list[object] = []

    async with TemporaryOverrideTestApp().run_test() as pilot:

        def on_dismiss(value: object) -> None:
            dismissed.append(value)

        pilot.app.push_screen(_DurationPickerModal(), callback=on_dismiss)
        await pilot.pause()

        await pilot.press("c")
        await pilot.pause()

        custom_input = pilot.app.screen.query_one(
            "#override-duration-custom-input", Input
        )
        custom_input.value = "not-a-duration"
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert dismissed == []
        error = pilot.app.screen.query_one("#override-duration-custom-error", Label)
        assert not error.has_class("hidden")


async def test_duration_modal_valid_custom_dismisses_with_seconds() -> None:
    """A valid custom duration dismisses with the parsed seconds."""
    result: object = "sentinel"

    async with TemporaryOverrideTestApp().run_test() as pilot:

        def on_dismiss(value: object) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(_DurationPickerModal(), callback=on_dismiss)
        await pilot.pause()

        await pilot.press("c")
        await pilot.pause()

        custom_input = pilot.app.screen.query_one(
            "#override-duration-custom-input", Input
        )
        custom_input.value = "1h30m"
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    assert result == 5400.0
