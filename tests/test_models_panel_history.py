"""Entry-resolution and footer wiring for Launch Control's ``H`` binding."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from textual.widgets import Static

import sase.ace.tui.modals.alias_history_modal as alias_history_modal
import sase.ace.tui.modals.models_panel_provider_state as models_panel_provider_state
import sase.ace.tui.modals.models_panel_providers as models_panel_providers
from sase.ace.tui.modals.alias_history_modal import AliasHistoryModal
from sase.ace.tui.modals.models_panel import ModelsPanel
from sase.ace.tui.modals.models_panel_rows import (
    BigEpicPhaseThresholdSettingRow,
    LaunchModelSettingRow,
)
from sase.llm_provider.alias_history import (
    AliasHistoryStatusRollup,
    AliasHistoryView,
)
from sase.llm_provider.config import (
    DEFAULT_MODEL_FIELD,
    LaunchModelSettingSnapshot,
)
from sase.llm_provider.model_launch_settings import LaunchModelField
from tests._models_panel_helpers import (
    ModelsPanelTestApp,
    highlight_row,
    make_alias_view,
    make_bucketed_views,
    patch_alias_views,
)


def _launch_setting_row(
    field: LaunchModelField,
    label: str,
    *,
    referenced_alias: str | None,
) -> LaunchModelSettingRow:
    return LaunchModelSettingRow(
        field=field,
        label=label,
        detail="detail",
        snapshot=LaunchModelSettingSnapshot(
            field=field,
            config_path=f"llm_provider.{field}",
            raw_value="@large" if referenced_alias else "claude/opus",
            provider="claude",
            model="opus",
            effort="high",
            provenance="shipped",
            referenced_alias=referenced_alias,
            override_key=f"setting:{field}",
        ),
    )


def _patch_launch_model_rows(
    monkeypatch,
    rows: tuple[LaunchModelSettingRow | BigEpicPhaseThresholdSettingRow, ...],
) -> None:
    """Pin both the initial and the async provider-snapshot launch rows.

    ``ModelsPanel`` reloads ``_launch_model_rows`` from a background worker
    right after mount (see ``on_mount`` -> ``_start_provider_snapshot_load``),
    which races and overwrites a plain post-construction attribute set. Both
    the initial and the reloaded snapshot go through
    ``build_launch_model_setting_rows``, so patching it in both importing
    modules pins the row deterministically end to end.
    """
    monkeypatch.setattr(
        models_panel_providers, "build_launch_model_setting_rows", lambda **_: rows
    )
    monkeypatch.setattr(
        models_panel_provider_state,
        "build_launch_model_setting_rows",
        lambda **_: rows,
    )


def _empty_view(*aliases: str) -> AliasHistoryView:
    return AliasHistoryView(
        index_path="/tmp/index.sqlite",
        aliases=aliases,
        limit_per_alias=10,
        include_hidden=False,
        projects=(),
        freshness="cached",
        groups=(),
        status_rollup=AliasHistoryStatusRollup(),
    )


@pytest.fixture(autouse=True)
def _stub_load_alias_history(monkeypatch) -> None:
    monkeypatch.setattr(
        alias_history_modal,
        "load_alias_history",
        lambda aliases, **kwargs: _empty_view(
            *(aliases if isinstance(aliases, tuple) else (aliases,))
        ),
    )


def test_h_binding_present_with_history_action() -> None:
    bindings = {key: action for key, action, *_ in ModelsPanel.BINDINGS}
    assert bindings["H"] == "alias_history"


@pytest.mark.parametrize(
    ("row_id", "expect_history"),
    [
        ("large", True),
        ("bucket:research", True),
        ("setting:default_effort", False),
        ("setting:runner_limit", False),
    ],
)
async def test_footer_shows_history_only_for_supported_rows(
    monkeypatch, row_id: str, expect_history: bool
) -> None:
    patch_alias_views(monkeypatch, make_bucketed_views())

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        highlight_row(panel, row_id)
        footer = str(panel.query_one("#models-panel-footer", Static).content)
        assert ("H" in footer and "History" in footer) is expect_history


async def test_footer_shows_history_for_alias_backed_launch_setting(
    monkeypatch,
) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("large", "role")])
    _patch_launch_model_rows(
        monkeypatch,
        (
            _launch_setting_row(
                DEFAULT_MODEL_FIELD, "launch model", referenced_alias="large"
            ),
            BigEpicPhaseThresholdSettingRow(5),
        ),
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        highlight_row(panel, "launch:default_model")
        footer = str(panel.query_one("#models-panel-footer", Static).content)
        assert "History" in footer


async def test_footer_hides_history_for_concrete_launch_setting(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("large", "role")])
    _patch_launch_model_rows(
        monkeypatch,
        (
            _launch_setting_row(
                DEFAULT_MODEL_FIELD, "launch model", referenced_alias=None
            ),
            BigEpicPhaseThresholdSettingRow(5),
        ),
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        highlight_row(panel, "launch:default_model")
        footer = str(panel.query_one("#models-panel-footer", Static).content)
        assert "History" not in footer


async def test_footer_hides_history_for_big_epic_threshold_row(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("large", "role")])

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        highlight_row(panel, "setting:big_epic_phase_threshold")
        footer = str(panel.query_one("#models-panel-footer", Static).content)
        assert "History" not in footer


async def test_h_on_alias_opens_history_modal_for_that_alias(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("large", "role")])

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        highlight_row(panel, "large")
        await pilot.press("H")
        await pilot.pause()

        assert isinstance(pilot.app.screen, AliasHistoryModal)
        entry = pilot.app.screen._entry
        assert entry.aliases == ("large",)
        assert entry.title_label == "@large"


async def test_h_on_bucket_opens_history_for_every_member_in_order(
    monkeypatch,
) -> None:
    patch_alias_views(monkeypatch, make_bucketed_views())

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        highlight_row(panel, "bucket:research")
        await pilot.press("H")
        await pilot.pause()

        assert isinstance(pilot.app.screen, AliasHistoryModal)
        entry = pilot.app.screen._entry
        assert entry.aliases == ("research_a", "research_b")
        assert entry.title_label == "research"


async def test_h_on_alias_backed_launch_setting_opens_referenced_alias(
    monkeypatch,
) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("large", "role")])
    _patch_launch_model_rows(
        monkeypatch,
        (
            _launch_setting_row(
                DEFAULT_MODEL_FIELD, "launch model", referenced_alias="large"
            ),
            BigEpicPhaseThresholdSettingRow(5),
        ),
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        highlight_row(panel, "launch:default_model")
        await pilot.press("H")
        await pilot.pause()

        assert isinstance(pilot.app.screen, AliasHistoryModal)
        entry = pilot.app.screen._entry
        assert entry.aliases == ("large",)


async def test_h_on_concrete_launch_setting_only_warns(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("large", "role")])
    _patch_launch_model_rows(
        monkeypatch,
        (
            _launch_setting_row(
                DEFAULT_MODEL_FIELD, "launch model", referenced_alias=None
            ),
            BigEpicPhaseThresholdSettingRow(5),
        ),
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(panel)
        await pilot.pause()
        highlight_row(panel, "launch:default_model")
        await pilot.press("H")
        await pilot.pause()

        assert pilot.app.screen is panel
        panel.notify.assert_called_once()
        assert "concrete model" in panel.notify.call_args.args[0]


@pytest.mark.parametrize(
    ("row_id", "expected_snippet"),
    [
        ("setting:default_effort", "default effort"),
        ("setting:runner_limit", "running agents"),
        ("setting:big_epic_phase_threshold", "big epic starts at"),
    ],
)
async def test_h_on_scalar_setting_only_warns(
    monkeypatch, row_id: str, expected_snippet: str
) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("large", "role")])

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(panel)
        await pilot.pause()
        highlight_row(panel, row_id)
        await pilot.press("H")
        await pilot.pause()

        assert pilot.app.screen is panel
        panel.notify.assert_called_once()
        assert expected_snippet in panel.notify.call_args.args[0]
