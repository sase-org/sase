"""Mounted Models-panel default-effort controls and persistent edit tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from textual.containers import Container
from textual.widgets import OptionList, Static

from sase.ace.testing import wait_for
import sase.ace.tui.modals.models_panel as models_panel
from sase.ace.tui.modals.models_panel import ModelsPanel
from sase.ace.tui.modals.models_panel_duration import DurationPickerModal
from sase.ace.tui.modals.models_panel_effort_cards import (
    DefaultEffortActionModal,
    DefaultEffortLevelChoice,
    DefaultEffortLevelModal,
)
from sase.ace.tui.modals.models_panel_effort_edit import (
    DefaultEffortEditPreviewModal,
    _plan_default_effort_edit,
)
from sase.config import ConfigLayer
from sase.llm_provider import (
    EffectiveDefaultEffortSnapshot,
    TemporaryEffortOverride,
)
from sase.xprompt.effort import EFFORT_LEVELS_ORDERED
from tests._models_panel_helpers import (
    ModelsPanelTestApp,
    StyledModelsPanelTestApp,
    make_alias_view,
    make_bucketed_views,
    make_edit_plan,
    patch_alias_views,
)

_NOW = 1_800_000_000.0


def _override(
    effort: str = "medium", *, expires_at: float | None = _NOW + 42 * 60
) -> TemporaryEffortOverride:
    return TemporaryEffortOverride(
        version=1,
        effort=effort,
        created_at=_NOW,
        expires_at=expires_at,
        source="test",
    )


def _snapshot(
    configured: str | None = "xhigh",
    override: TemporaryEffortOverride | None = None,
) -> EffectiveDefaultEffortSnapshot:
    return EffectiveDefaultEffortSnapshot(
        configured_effort=configured,
        temporary_override=override,
        captured_at=_NOW,
    )


def _patch_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: EffectiveDefaultEffortSnapshot,
    *,
    use_chezmoi: bool = False,
) -> None:
    monkeypatch.setattr(models_panel, "_now", lambda: _NOW)
    monkeypatch.setattr(
        ModelsPanel,
        "_load_effective_effort_snapshot",
        lambda self: (snapshot, use_chezmoi),
    )


@pytest.mark.parametrize("bucket_state", ["alias", "collapsed", "open"])
async def test_ctrl_e_opens_global_action_card_in_every_bucket_state(
    monkeypatch: pytest.MonkeyPatch, bucket_state: str
) -> None:
    views = make_bucketed_views()
    patch_alias_views(monkeypatch, views)
    _patch_snapshot(monkeypatch, _snapshot())

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        if bucket_state in {"collapsed", "open"}:
            await pilot.press("j", "j")
        if bucket_state == "open":
            await pilot.press("l")
        await pilot.press("ctrl+e")
        assert isinstance(pilot.app.screen, DefaultEffortActionModal)


async def test_panel_title_and_chooser_show_effective_and_configured_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("default", "default")])
    _patch_snapshot(monkeypatch, _snapshot(override=_override()))

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        title = panel.query_one("#models-panel-title", Static).content.plain
        assert title == (
            "Models\ndefault effort: @ medium  override · 42m left  configured @ xhigh"
            "\nmax running agents: 10"
        )
        assert (
            "[green]ctrl+e[/green]=Effort"
            in panel.query_one("#models-panel-footer", Static).content
        )
        await pilot.press("ctrl+e")
        status = pilot.app.screen.query_one(
            "#default-effort-action-status", Static
        ).content.plain
        assert "Current for new launches\n@ medium  override · 42m left" in status
        assert "Configured: @ xhigh" in status
        assert len(pilot.app.screen.query(".default-effort-action-row")) == 3


async def test_chooser_hides_clear_without_active_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_snapshot(monkeypatch, _snapshot(override=None))
    async with ModelsPanelTestApp().run_test() as pilot:
        pilot.app.push_screen(
            DefaultEffortActionModal(_snapshot(), now=_NOW, use_chezmoi=True)
        )
        await pilot.pause()
        assert len(pilot.app.screen.query(".default-effort-action-row")) == 2
        assert (
            "chezmoi source"
            in pilot.app.screen.query_one(".default-effort-action-row", Static).content
        )


@pytest.mark.parametrize("mode", ["edit", "override"])
async def test_level_picker_uses_canonical_single_key_ladder(
    mode: str,
) -> None:
    async with ModelsPanelTestApp().run_test() as pilot:
        pilot.app.push_screen(
            DefaultEffortLevelModal(  # type: ignore[arg-type]
                mode, _snapshot(override=_override()), now=_NOW
            )
        )
        await pilot.pause()
        option_list = pilot.app.screen.query_one(
            "#default-effort-level-list", OptionList
        )
        rows = [option.prompt.plain for option in option_list.options]
        expected = list(EFFORT_LEVELS_ORDERED)
        if mode == "edit":
            assert "provider default" in rows[0]
            rows = rows[1:]
        assert [row.split()[1] for row in rows] == expected
        assert any("override · current" in row for row in rows)
        highlighted = option_list.highlighted
        assert highlighted is not None
        assert option_list.get_option_at_index(highlighted).id == "xhigh"


async def test_model_effort_picker_enter_uses_configured_not_temporary() -> None:
    captured: list[DefaultEffortLevelChoice | None] = []
    async with ModelsPanelTestApp().run_test() as pilot:
        pilot.app.push_screen(
            DefaultEffortLevelModal(
                "model",
                _snapshot("xhigh", override=_override("medium")),
                now=_NOW,
                model="@medium_worker",
            ),
            captured.append,
        )
        await pilot.pause()
        option_list = pilot.app.screen.query_one(
            "#default-effort-level-list", OptionList
        )
        highlighted = option_list.highlighted
        assert highlighted is not None
        assert option_list.get_option_at_index(highlighted).id == "xhigh"
        await pilot.press("enter")
        await pilot.pause()

    assert [choice.effort for choice in captured] == ["xhigh"]


async def test_model_effort_picker_without_config_defaults_to_no_suffix() -> None:
    captured: list[DefaultEffortLevelChoice | None] = []
    async with ModelsPanelTestApp().run_test() as pilot:
        pilot.app.push_screen(
            DefaultEffortLevelModal(
                "model",
                _snapshot(None, override=_override("medium")),
                now=_NOW,
                model="codex/o3",
            ),
            captured.append,
        )
        await pilot.pause()
        option_list = pilot.app.screen.query_one(
            "#default-effort-level-list", OptionList
        )
        highlighted = option_list.highlighted
        assert highlighted is not None
        assert option_list.get_option_at_index(highlighted).id == (
            "__provider_default__"
        )
        await pilot.press("enter")
        await pilot.pause()

    assert [choice.effort for choice in captured] == [None]


async def test_override_flow_reuses_duration_picker_and_updates_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("default", "default")])
    _patch_snapshot(monkeypatch, _snapshot(override=None))

    def set_override(
        self: ModelsPanel, effort: str, seconds: float | None
    ) -> TemporaryEffortOverride:
        assert effort == "medium"
        assert seconds == 15 * 60.0
        return _override("medium", expires_at=_NOW + 15 * 60)

    monkeypatch.setattr(ModelsPanel, "_set_default_effort_override", set_override)

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        await pilot.press("ctrl+e", "o", "4")
        assert isinstance(pilot.app.screen, DurationPickerModal)
        await pilot.press("1")
        await wait_for(pilot, lambda: panel._effort_override_worker is None)
        assert panel._effort_snapshot.effective_effort(_NOW) == "medium"
        assert panel._highlighted_row_id() == "default"


async def test_clear_flow_preserves_alias_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_alias_views(
        monkeypatch,
        [
            make_alias_view("default", "default"),
            make_alias_view(
                "plain",
                "user",
                configured=True,
                configured_source="custom",
            ),
        ],
    )
    _patch_snapshot(monkeypatch, _snapshot(override=_override()))
    monkeypatch.setattr(
        ModelsPanel, "_clear_default_effort_override", lambda self: True
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        await pilot.press("j", "ctrl+e", "x")
        await wait_for(pilot, lambda: panel._effort_clear_worker is None)
        assert panel._effort_snapshot.temporary_override is None
        assert panel._highlighted_row_id() == "plain"


async def test_new_cards_fit_narrow_supported_layout() -> None:
    async with StyledModelsPanelTestApp().run_test(size=(80, 40)) as pilot:
        pilot.app.push_screen(DefaultEffortLevelModal("edit", _snapshot(), now=_NOW))
        await pilot.pause()
        container = pilot.app.screen.query_one(
            "#default-effort-level-container", Container
        )
        assert container.region.x >= 0
        assert container.region.right <= pilot.app.screen.size.width
        assert container.region.bottom <= pilot.app.screen.size.height


def test_persistent_edit_targets_user_base_and_preserves_yaml(
    tmp_path: Path,
) -> None:
    user_file = tmp_path / "sase.yml"
    user_file.write_text(
        "# top\nllm_provider:\n  # keep me\n  default_effort: low\n  "
        "model_aliases: {}\n",
        encoding="utf-8",
    )
    layers = [
        ConfigLayer(
            name="default",
            path=None,
            exists=True,
            list_strategy="concatenate",
            data={},
        ),
        ConfigLayer(
            name="user",
            path=str(user_file),
            exists=True,
            list_strategy="replace",
            data={
                "llm_provider": {
                    "default_effort": "low",
                    "model_aliases": {},
                }
            },
        ),
        ConfigLayer(
            name="local",
            path=str(tmp_path / "project" / "sase.yml"),
            exists=True,
            list_strategy="concatenate",
            data={"llm_provider": {"default_effort": "max"}},
        ),
    ]
    with patch("sase.config.inventory.load_config_layers", return_value=layers):
        plan = _plan_default_effort_edit("xhigh", use_chezmoi=False)
    assert plan.write_plan.layer == "user"
    assert plan.target_path == str(user_file)
    assert "# keep me" in plan.new_text
    assert "default_effort: xhigh" in plan.new_text
    assert str(tmp_path / "project") not in (plan.target_path or "")


async def test_edit_preview_warns_when_temporary_override_remains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.models_panel_effort_edit._plan_default_effort_edit",
        lambda effort: make_edit_plan(value=effort),
    )
    async with ModelsPanelTestApp().run_test() as pilot:
        pilot.app.push_screen(
            DefaultEffortEditPreviewModal("high", override_active=True)
        )
        await pilot.pause()
        preview = pilot.app.screen.query_one(
            "#alias-edit-preview", Static
        ).content.plain
        assert "llm_provider.default_effort" in preview
        assert "remains launch-effective until it expires or is cleared" in preview
