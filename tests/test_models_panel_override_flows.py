"""Models panel override action and modal-flow tests."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import sase.ace.tui.modals.models_panel as models_panel
from sase.ace.tui.modals.custom_model_input_modal import CustomModelInputModal
from sase.ace.tui.modals.model_picker_modal import (
    CUSTOM_SENTINEL,
    AliasSelectionContext,
    ModelPickerModal,
)
from sase.ace.tui.modals.models_panel import (
    ModelsPanel,
    ModelsPanelResult,
    _DurationPickerModal,
)
from sase.ace.tui.modals.models_panel_duration import (
    OPEN_OVERRIDE_UNTIL,
    RelativeOverrideDuration,
)
from sase.ace.tui.modals.models_panel_time import (
    OVERRIDE_UNTIL_BACK,
    OverrideUntilModal,
    ResolvedOverrideUntil,
)
from sase.llm_provider import TemporaryLLMOverride
from tests._models_panel_helpers import (
    ModelsPanelTestApp,
    make_alias_view,
    patch_alias_views,
)


def test_action_close_dismisses_unchanged() -> None:
    panel = ModelsPanel()
    panel.dismiss = MagicMock()  # type: ignore[method-assign,assignment]
    panel.action_close()
    (arg,), _ = panel.dismiss.call_args
    assert isinstance(arg, ModelsPanelResult)
    assert arg.changed is False


def test_on_duration_picked_cancel_is_noop(monkeypatch) -> None:
    panel = ModelsPanel()
    panel._refresh_rows = MagicMock()  # type: ignore[method-assign]
    set_mock = MagicMock()
    monkeypatch.setattr(models_panel, "set_alias_override", set_mock)
    panel._on_duration_picked(models_panel.DURATION_CHOICE_CANCELLED)
    set_mock.assert_not_called()
    assert panel._changed is False


async def test_action_override_opens_alias_enabled_picker(monkeypatch) -> None:
    views = [
        make_alias_view("coder", "role"),
        make_alias_view(
            "bucketed",
            "user",
            configured=True,
            configured_source="custom",
            bucket="research",
        ),
    ]
    patch_alias_views(monkeypatch, views)

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        await pilot.press("l", "o")
        await pilot.pause()

        picker = pilot.app.screen
        assert isinstance(picker, ModelPickerModal)
        assert picker._alias_context is not None
        assert picker._alias_context.operation == "temporary"
        assert picker._alias_context.views == tuple(views)
        assert "@bucketed" in {row.option_id for row in picker._all_rows}


async def test_on_duration_picked_invalid_notifies_error(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("coder", "role")])
    monkeypatch.setattr(
        models_panel,
        "set_alias_override",
        MagicMock(side_effect=ValueError("nope")),
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_alias = "coder"
        panel._pending_raw_model = "bad"
        panel._on_duration_picked(RelativeOverrideDuration(60.0))
        await pilot.pause()
        await pilot.pause()
        assert panel._changed is False
        panel.notify.assert_called_once()
        assert panel.notify.call_args.kwargs.get("severity") == "error"


async def test_set_flow_threads_model_and_duration(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("coder", "role")])
    fake = TemporaryLLMOverride(
        provider="codex",
        model="o3",
        raw_model="o3",
        created_at=0.0,
        expires_at=3600.0,
        source="ace",
    )
    set_mock = MagicMock(return_value=fake)
    monkeypatch.setattr(models_panel, "set_alias_override", set_mock)

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_alias = "coder"
        panel._on_model_picked("o3")
        await pilot.pause()
        assert isinstance(pilot.app.screen, _DurationPickerModal)
        panel._on_duration_picked(RelativeOverrideDuration(3600.0))
        await pilot.pause()

    set_mock.assert_called_once_with("coder", "o3", 3600.0, source="ace")
    assert panel._changed is True


async def test_alias_override_flows_raw_token_through_write_time_resolution(
    monkeypatch,
) -> None:
    target = make_alias_view("phase_worker", "role")
    coder = make_alias_view("coder", "role", provider="codex", model="o3")
    patch_alias_views(monkeypatch, [target, coder])
    fake = TemporaryLLMOverride(
        provider="codex",
        model="o3",
        raw_model="@coder",
        created_at=0.0,
        expires_at=3600.0,
        source="ace",
    )
    set_mock = MagicMock(return_value=fake)
    monkeypatch.setattr(models_panel, "set_alias_override", set_mock)

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_alias = target.name
        panel._pending_alias_selection = AliasSelectionContext(
            (target, coder), target.name, "temporary"
        )
        panel._on_model_picked("@coder")
        await pilot.pause()
        assert isinstance(pilot.app.screen, _DurationPickerModal)
        assert panel._pending_raw_model == "@coder"
        panel._on_duration_picked(RelativeOverrideDuration(3600.0))
        await pilot.pause()

    set_mock.assert_called_once_with("phase_worker", "@coder", 3600.0, source="ace")
    assert fake.raw_model == "@coder"


async def test_custom_override_rejects_self_alias(monkeypatch) -> None:
    target = make_alias_view("coder", "role")
    patch_alias_views(monkeypatch, [target])

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_alias = target.name
        panel._pending_alias_selection = AliasSelectionContext(
            (target,), target.name, "temporary"
        )
        panel._on_custom_picked("@coder")
        await pilot.pause()

        assert isinstance(pilot.app.screen, ModelsPanel)
        panel.notify.assert_called_once()
        assert "current alias" in panel.notify.call_args.args[0]


async def test_t_opens_until_modal_and_back_reopens_duration(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("coder", "role")])

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_alias = "coder"
        panel._pending_raw_model = "o3"
        panel._on_duration_picked(OPEN_OVERRIDE_UNTIL)
        await pilot.pause()
        assert isinstance(pilot.app.screen, OverrideUntilModal)
        panel._on_override_until_picked(OVERRIDE_UNTIL_BACK)
        await pilot.pause()
        assert isinstance(pilot.app.screen, _DurationPickerModal)


async def test_exact_time_flow_dispatches_exact_api(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("coder", "role")])
    fake = TemporaryLLMOverride(
        provider="codex",
        model="o3",
        raw_model="o3",
        created_at=1000.0,
        expires_at=2000.0,
        source="ace",
    )
    exact_set = MagicMock(return_value=fake)
    relative_set = MagicMock()
    monkeypatch.setattr(models_panel, "set_alias_override_until", exact_set)
    monkeypatch.setattr(models_panel, "set_alias_override", relative_set)
    resolved = ResolvedOverrideUntil(
        target=datetime.fromtimestamp(2000, UTC),
        expires_at=2000.0,
        target_display="Ends Thu Jan 1 at 12:33 AM EST",
        notification_display="Thu Jan 1, 12:33 AM EST",
        remaining_display="16m",
        timezone_display="America/New_York",
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_alias = "coder"
        panel._pending_raw_model = "o3"
        panel._on_override_until_picked(resolved)
        await pilot.pause()
        await pilot.pause()

    exact_set.assert_called_once_with("coder", "o3", 2000.0, source="ace")
    relative_set.assert_not_called()
    assert panel._changed is True


async def test_custom_model_path_opens_input_then_duration(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("coder", "role")])

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_alias = "coder"
        panel._on_model_picked(CUSTOM_SENTINEL)
        await pilot.pause()
        assert isinstance(pilot.app.screen, CustomModelInputModal)
        panel._on_custom_picked("codex/o3")
        await pilot.pause()
        assert isinstance(pilot.app.screen, _DurationPickerModal)
        assert panel._pending_raw_model == "codex/o3"
