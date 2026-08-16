"""Launch Control big-epic threshold row and edit workflow tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from textual.widgets import Input, OptionList, Static

from sase.ace.testing import wait_for
from sase.ace.tui.modals.models_panel import ModelsPanel
from sase.ace.tui.modals.models_panel_provider_state import ProviderRoutingSnapshot
from sase.ace.tui.modals.models_panel_threshold_cards import (
    BigEpicPhaseThresholdValueModal,
    _parse_big_epic_phase_threshold,
)
from sase.ace.tui.modals.models_panel_threshold_edit import (
    BIG_EPIC_PHASE_THRESHOLD_FIELD_PATH,
    BigEpicPhaseThresholdEditOutcome,
    BigEpicPhaseThresholdEditPreviewModal,
    _plan_big_epic_phase_threshold_edit,
)
from sase.config import AppliedResult, ConfigEditOp, ConfigLayer
from tests._models_panel_helpers import (
    ModelsPanelTestApp,
    make_alias_view,
    patch_alias_views,
)


def _highlight_row(panel: ModelsPanel, row_id: str) -> None:
    option_list = panel.query_one("#models-panel-list", OptionList)
    panel._set_highlighted_index(option_list, option_list.get_option_index(row_id))
    panel._update_context()


@pytest.mark.parametrize(
    "raw",
    ["", "0", "-1", "+1", "1.5", " 1", "1 ", "True", "four"],
)
def test_threshold_parser_rejects_invalid_input(raw: str) -> None:
    with pytest.raises(ValueError):
        _parse_big_epic_phase_threshold(raw)


@pytest.mark.parametrize("raw, expected", [("1", 1), ("5", 5), ("0012", 12)])
def test_threshold_parser_accepts_positive_decimal(raw: str, expected: int) -> None:
    assert _parse_big_epic_phase_threshold(raw) == expected


async def test_threshold_value_card_prefills_selects_and_validates() -> None:
    results: list[int | None] = []
    async with ModelsPanelTestApp().run_test() as pilot:
        pilot.app.push_screen(
            BigEpicPhaseThresholdValueModal(initial=5), callback=results.append
        )
        await pilot.pause()
        value_input = pilot.app.screen.query_one(
            "#big-epic-threshold-value-input", Input
        )
        assert value_input.value == "5"
        value_input.value = "0"
        await pilot.press("enter")
        assert isinstance(pilot.app.screen, BigEpicPhaseThresholdValueModal)
        assert (
            "at least 1"
            in pilot.app.screen.query_one(
                "#big-epic-threshold-value-error", Static
            ).content
        )
        value_input.value = "1"
        await pilot.press("enter")
        await pilot.pause()
        assert results == [1]


def test_threshold_plan_targets_user_base_and_config_path(tmp_path: Path) -> None:
    user_file = tmp_path / "sase.yml"
    user_file.write_text(
        "# top\nbead:\n  big_epic_phase_threshold: 5\n",
        encoding="utf-8",
    )
    local_file = tmp_path / "project" / "sase.yml"
    layers = [
        ConfigLayer(
            name="default",
            path=None,
            exists=True,
            list_strategy="concatenate",
            data={"bead": {"big_epic_phase_threshold": 5}},
        ),
        ConfigLayer(
            name="user",
            path=str(user_file),
            exists=True,
            list_strategy="replace",
            data={"bead": {"big_epic_phase_threshold": 5}},
        ),
        ConfigLayer(
            name="local",
            path=str(local_file),
            exists=True,
            list_strategy="concatenate",
            data={"bead": {"big_epic_phase_threshold": 9}},
        ),
    ]
    with patch("sase.config.inventory.load_config_layers", return_value=layers):
        plan = _plan_big_epic_phase_threshold_edit(
            ConfigEditOp.set_value(7),
            use_chezmoi=False,
        )

    assert plan.write_plan.layer == "user"
    assert plan.write_plan.key_path == ("bead", "big_epic_phase_threshold")
    assert plan.effective_preview.path == BIG_EPIC_PHASE_THRESHOLD_FIELD_PATH
    assert plan.target_path == str(user_file)
    assert "big_epic_phase_threshold: 7" in plan.new_text
    assert plan.effective_preview.after == 9


def test_threshold_reset_uses_unset_planning(tmp_path: Path) -> None:
    user_file = tmp_path / "sase.yml"
    user_file.write_text("bead:\n  big_epic_phase_threshold: 8\n", encoding="utf-8")
    layers = [
        ConfigLayer(
            name="default",
            path=None,
            exists=True,
            list_strategy="concatenate",
            data={"bead": {"big_epic_phase_threshold": 5}},
        ),
        ConfigLayer(
            name="user",
            path=str(user_file),
            exists=True,
            list_strategy="replace",
            data={"bead": {"big_epic_phase_threshold": 8}},
        ),
    ]
    with patch("sase.config.inventory.load_config_layers", return_value=layers):
        plan = _plan_big_epic_phase_threshold_edit(
            ConfigEditOp.unset(),
            use_chezmoi=False,
        )

    assert plan.write_plan.op == "unset"
    assert "big_epic_phase_threshold" not in plan.new_text
    assert plan.effective_preview.after == 5


def test_threshold_schema_rejects_minimum_violation(tmp_path: Path) -> None:
    user_file = tmp_path / "sase.yml"
    user_file.write_text("bead: {}\n", encoding="utf-8")
    layers = [
        ConfigLayer(
            name="default",
            path=None,
            exists=True,
            list_strategy="concatenate",
            data={"bead": {"big_epic_phase_threshold": 5}},
        ),
        ConfigLayer(
            name="user",
            path=str(user_file),
            exists=True,
            list_strategy="replace",
            data={"bead": {}},
        ),
    ]
    with patch("sase.config.inventory.load_config_layers", return_value=layers):
        plan = _plan_big_epic_phase_threshold_edit(
            ConfigEditOp.set_value(0),
            use_chezmoi=False,
        )

    assert not plan.is_valid
    assert any(
        "minimum" in diagnostic.message.lower() for diagnostic in plan.validation
    )


async def test_threshold_row_order_description_footer_and_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("large", "role")])

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(panel)
        await pilot.pause()
        option_list = panel.query_one("#models-panel-list", OptionList)
        ids = [
            option_list.get_option_at_index(index).id
            for index in range(option_list.option_count)
        ]
        assert (
            ids.index("setting:big_epic_phase_threshold")
            == ids.index("launch:big_epic_lander_model") + 1
        )
        _highlight_row(panel, "setting:big_epic_phase_threshold")
        description = panel.query_one("#models-panel-description", Static).content.plain
        assert "5 or more authored phases use the big epic lander" in description
        assert "bead.big_epic_phase_threshold: 5" in description
        footer = str(panel.query_one("#models-panel-footer", Static).content)
        assert "e/enter[/green]=Edit" in footer
        assert "[green]r[/green]=Reset" in footer
        assert "[green]o[/green]=Override" not in footer

        await pilot.press("o")
        panel.notify.assert_called_once_with(
            "big epic starts at has no temporary override; press e to edit "
            "or r to reset.",
            severity="warning",
        )
        panel.notify.reset_mock()
        await pilot.press("x")
        panel.notify.assert_called_once()

        await pilot.press("e")
        assert isinstance(pilot.app.screen, BigEpicPhaseThresholdValueModal)
        await pilot.press("escape")
        await pilot.press("r")
        assert isinstance(pilot.app.screen, BigEpicPhaseThresholdEditPreviewModal)


async def test_threshold_edit_refreshes_atomic_snapshot_and_reports_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    views = [make_alias_view("large", "role")]
    patch_alias_views(monkeypatch, views)

    def load_snapshot(self: ModelsPanel) -> ProviderRoutingSnapshot:
        from sase.ace.tui.modals.models_panel_rows import (
            build_launch_model_setting_rows,
        )

        return ProviderRoutingSnapshot(
            statuses=(),
            provider_disables={},
            alias_views=tuple(views),
            provider_colors={},
            captured_at=0.0,
            launch_model_rows=build_launch_model_setting_rows(
                provider_disables={},
                big_epic_phase_threshold=9,
            ),
            big_epic_phase_threshold=9,
        )

    monkeypatch.setattr(ModelsPanel, "_load_provider_routing_snapshot", load_snapshot)
    monkeypatch.setattr(
        ModelsPanel,
        "_build_big_epic_phase_threshold_commit_offer",
        lambda self, _path: None,
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        panel.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(panel)
        await pilot.pause()
        _highlight_row(panel, "setting:big_epic_phase_threshold")
        panel._on_big_epic_phase_threshold_edited(
            BigEpicPhaseThresholdEditOutcome(
                requested_threshold=7,
                effective_threshold=9,
                applied=AppliedResult(
                    path="/tmp/sase.yml",
                    op="set",
                    key_path=("bead", "big_epic_phase_threshold"),
                    created=False,
                    used_chezmoi=False,
                ),
            )
        )
        await wait_for(pilot, lambda: panel._provider_snapshot_worker is None)

        assert panel._changed is True
        assert panel._highlighted_row_id() == "setting:big_epic_phase_threshold"
        description = panel.query_one("#models-panel-description", Static).content.plain
        assert "9 or more authored phases" in description
        panel.notify.assert_any_call(
            "Configured big-epic threshold: 9 "
            "(requested 7; higher-precedence config still wins)"
        )
