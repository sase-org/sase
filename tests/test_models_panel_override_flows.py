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
from sase.ace.tui.modals.models_panel_effort_cards import (
    DefaultEffortLevelChoice,
    DefaultEffortLevelModal,
)
from sase.ace.tui.modals.models_panel_time import (
    OVERRIDE_UNTIL_BACK,
    OverrideUntilModal,
    ResolvedOverrideUntil,
)
from sase.llm_provider import TemporaryLLMOverride, TemporaryProviderDisable
from sase.llm_provider.provider_disable import PROVIDER_DISABLE_WIRE_SCHEMA_VERSION
from tests._models_panel_helpers import (
    ModelsPanelTestApp,
    make_alias_view,
    make_pool_members,
    patch_alias_views,
)


def _disable(provider: str) -> TemporaryProviderDisable:
    return TemporaryProviderDisable(
        version=PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
        provider=provider,
        created_at=100.0,
        expires_at=None,
        source="test",
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
        make_alias_view("medium_worker", "role"),
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
        disable = _disable("codex")
        panel._provider_disables = {"codex": disable}
        await pilot.press("l", "o")
        await pilot.pause()

        picker = pilot.app.screen
        assert isinstance(picker, ModelPickerModal)
        assert picker._alias_context is not None
        assert picker._alias_context.operation == "temporary"
        assert picker._alias_context.views == tuple(views)
        assert picker._provider_disables == {"codex": disable}
        assert "@bucketed" in {row.option_id for row in picker._all_rows}


async def test_on_duration_picked_invalid_notifies_error(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("medium_worker", "role")])
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
        panel._pending_alias = "medium_worker"
        panel._pending_raw_model = "bad"
        panel._on_duration_picked(RelativeOverrideDuration(60.0))
        await pilot.pause()
        await pilot.pause()
        assert panel._changed is False
        panel.notify.assert_called_once()
        assert panel.notify.call_args.kwargs.get("severity") == "error"


async def test_set_flow_threads_model_and_duration(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("medium_worker", "role")])
    fake = TemporaryLLMOverride(
        provider="codex",
        model="o3",
        raw_model="o3",
        created_at=0.0,
        expires_at=3600.0,
        source="ace",
        effort="medium",
    )
    set_mock = MagicMock(return_value=fake)
    monkeypatch.setattr(models_panel, "set_alias_override", set_mock)

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_alias = "medium_worker"
        panel._on_model_picked("o3")
        await pilot.pause()
        assert isinstance(pilot.app.screen, DefaultEffortLevelModal)
        panel._on_override_model_effort_picked(DefaultEffortLevelChoice("medium"))
        await pilot.pause()
        assert isinstance(pilot.app.screen, _DurationPickerModal)
        panel._on_duration_picked(RelativeOverrideDuration(3600.0))
        await pilot.pause()

    set_mock.assert_called_once_with("medium_worker", "o3@medium", 3600.0, source="ace")
    assert "CODEX(o3)@medium" in panel.notify.call_args.args[0]
    assert panel._changed is True


async def test_alias_override_flows_raw_token_through_write_time_resolution(
    monkeypatch,
) -> None:
    target = make_alias_view("large_worker", "role")
    medium_worker = make_alias_view(
        "medium_worker", "role", provider="codex", model="o3"
    )
    patch_alias_views(monkeypatch, [target, medium_worker])
    fake = TemporaryLLMOverride(
        provider="codex",
        model="o3",
        raw_model="@medium_worker@medium",
        created_at=0.0,
        expires_at=3600.0,
        source="ace",
        effort="medium",
    )
    set_mock = MagicMock(return_value=fake)
    monkeypatch.setattr(models_panel, "set_alias_override", set_mock)

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_alias = target.name
        panel._pending_alias_selection = AliasSelectionContext(
            (target, medium_worker), target.name, "temporary"
        )
        panel._on_model_picked("@medium_worker")
        await pilot.pause()
        assert isinstance(pilot.app.screen, DefaultEffortLevelModal)
        panel._on_override_model_effort_picked(DefaultEffortLevelChoice("medium"))
        await pilot.pause()
        assert isinstance(pilot.app.screen, _DurationPickerModal)
        assert panel._pending_raw_model == "@medium_worker@medium"
        panel._on_duration_picked(RelativeOverrideDuration(3600.0))
        await pilot.pause()

    set_mock.assert_called_once_with(
        "large_worker", "@medium_worker@medium", 3600.0, source="ace"
    )
    assert fake.raw_model == "@medium_worker@medium"


async def test_custom_override_rejects_self_alias(monkeypatch) -> None:
    target = make_alias_view("medium_worker", "role")
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
        panel._on_custom_picked("@medium_worker")
        await pilot.pause()

        assert isinstance(pilot.app.screen, ModelsPanel)
        panel.notify.assert_called_once()
        assert "current alias" in panel.notify.call_args.args[0]


async def test_custom_override_rejects_round_robin_selector(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("medium_worker", "role")])

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_alias = "medium_worker"
        panel._on_custom_picked("claude/opus | codex/gpt-5.5")
        await pilot.pause()

        assert isinstance(pilot.app.screen, ModelsPanel)
        panel.notify.assert_called_once()
        message, kwargs = panel.notify.call_args.args[0], panel.notify.call_args.kwargs
        assert "@medium_worker" in message
        assert "Press e" in message
        assert kwargs["severity"] == "warning"


async def test_custom_override_rejects_disabled_explicit_provider(
    monkeypatch,
) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("medium_worker", "role")])

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_alias = "medium_worker"
        panel._provider_disables = {"codex": _disable("codex")}
        panel._on_custom_picked("codex/o3@medium")
        await pilot.pause()

        assert isinstance(pilot.app.screen, ModelsPanel)
        assert panel._pending_raw_model == ""
        panel.notify.assert_called_once()
        message = panel.notify.call_args.args[0]
        assert "Cannot use codex/o3@medium" in message
        assert "CODEX is temporarily disabled until cleared" in message
        assert panel.notify.call_args.kwargs["severity"] == "warning"


async def test_custom_override_rejects_fallback_selector(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("medium_worker", "role")])

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_alias = "medium_worker"
        panel._on_custom_picked("claude/opus || codex/gpt-5.5")
        await pilot.pause()

        assert isinstance(pilot.app.screen, ModelsPanel)
        panel.notify.assert_called_once()
        message, kwargs = panel.notify.call_args.args[0], panel.notify.call_args.kwargs
        assert "@medium_worker" in message
        assert "Press e" in message
        assert kwargs["severity"] == "warning"


async def test_custom_override_rejects_mixed_selector_syntax(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("medium_worker", "role")])

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_alias = "medium_worker"
        panel._on_custom_picked("claude/opus | codex/gpt-5.5 || o3")
        await pilot.pause()

        assert isinstance(pilot.app.screen, ModelsPanel)
        panel.notify.assert_called_once()
        message, kwargs = panel.notify.call_args.args[0], panel.notify.call_args.kwargs
        assert "mix" in message
        assert kwargs["severity"] == "warning"


async def test_alias_reference_to_pool_owning_alias_still_snapshots(
    monkeypatch,
) -> None:
    target = make_alias_view("medium_worker", "role")
    pool_owner = make_alias_view(
        "pool_alias",
        "user",
        selector_mode="round_robin",
        selector_members=make_pool_members(),
    )
    patch_alias_views(monkeypatch, [target, pool_owner])

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_alias = target.name
        panel._pending_alias_selection = AliasSelectionContext(
            (target, pool_owner), target.name, "temporary"
        )
        panel._on_model_picked("@pool_alias")
        await pilot.pause()

        assert isinstance(pilot.app.screen, DefaultEffortLevelModal)
        assert panel._pending_raw_model == "@pool_alias"


async def test_t_opens_until_modal_and_back_reopens_duration(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("medium_worker", "role")])

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_alias = "medium_worker"
        panel._pending_raw_model = "o3"
        panel._on_duration_picked(OPEN_OVERRIDE_UNTIL)
        await pilot.pause()
        assert isinstance(pilot.app.screen, OverrideUntilModal)
        panel._on_override_until_picked(OVERRIDE_UNTIL_BACK)
        await pilot.pause()
        assert isinstance(pilot.app.screen, _DurationPickerModal)


async def test_exact_time_flow_dispatches_exact_api(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("medium_worker", "role")])
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
        panel._pending_alias = "medium_worker"
        panel._pending_raw_model = "o3"
        panel._on_override_until_picked(resolved)
        await pilot.pause()
        await pilot.pause()

    exact_set.assert_called_once_with("medium_worker", "o3", 2000.0, source="ace")
    relative_set.assert_not_called()
    assert panel._changed is True


async def test_custom_model_path_opens_input_then_duration(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("medium_worker", "role")])

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_alias = "medium_worker"
        panel._on_model_picked(CUSTOM_SENTINEL)
        await pilot.pause()
        assert isinstance(pilot.app.screen, CustomModelInputModal)
        panel._on_custom_picked("codex/o3")
        await pilot.pause()
        assert isinstance(pilot.app.screen, DefaultEffortLevelModal)
        panel._on_override_model_effort_picked(DefaultEffortLevelChoice(None))
        await pilot.pause()
        assert isinstance(pilot.app.screen, _DurationPickerModal)
        assert panel._pending_raw_model == "codex/o3"


async def test_custom_override_explicit_effort_skips_effort_picker(
    monkeypatch,
) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("medium_worker", "role")])

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_alias = "medium_worker"
        panel._on_custom_picked("codex/o3@medium")
        await pilot.pause()

        assert isinstance(pilot.app.screen, _DurationPickerModal)
        assert panel._pending_raw_model == "codex/o3@medium"


async def test_custom_alias_override_explicit_effort_skips_effort_picker(
    monkeypatch,
) -> None:
    target = make_alias_view("medium_worker", "role")
    default = make_alias_view("default", "default")
    patch_alias_views(monkeypatch, [target, default])

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_alias = "medium_worker"
        panel._pending_alias_selection = AliasSelectionContext(
            (target, default), target.name, "temporary"
        )
        panel._on_custom_picked("@default@medium")
        await pilot.pause()

        assert isinstance(pilot.app.screen, _DurationPickerModal)
        assert panel._pending_raw_model == "@default@medium"


async def test_override_effort_cancel_does_not_open_duration(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("medium_worker", "role")])

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        panel._pending_alias = "medium_worker"
        panel._on_model_picked("o3")
        await pilot.pause()
        assert isinstance(pilot.app.screen, DefaultEffortLevelModal)
        panel._on_override_model_effort_picked(None)
        await pilot.pause()

        assert isinstance(pilot.app.screen, DefaultEffortLevelModal)
