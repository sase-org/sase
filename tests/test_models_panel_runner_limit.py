"""Mounted Models-panel maximum-running-agents controls."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from textual.containers import Container
from textual.widgets import Input, Static

import sase.ace.tui.modals.models_panel as models_panel
from sase.ace.tui.modals.models_panel import ModelsPanel
from sase.ace.tui.modals.models_panel_duration import DurationPickerModal
from sase.ace.tui.modals.models_panel_runner_limit_cards import (
    RunnerLimitActionModal,
    RunnerLimitValueModal,
    _parse_runner_limit,
)
from sase.ace.tui.modals.models_panel_runner_limit_edit import (
    RunnerLimitEditPreviewModal,
    _plan_runner_limit_edit,
)
from sase.config import (
    ConfigLayer,
    EffectiveRunnerLimitSnapshot,
    TemporaryRunnerLimitOverride,
)
from tests._models_panel_helpers import (
    ModelsPanelTestApp,
    StyledModelsPanelTestApp,
    make_alias_view,
    make_bucketed_views,
    make_edit_plan,
    patch_alias_views,
)

_NOW = 1_800_000_000.0


class _RefreshingModelsPanelTestApp(ModelsPanelTestApp):
    def __init__(self) -> None:
        super().__init__()
        self.refresh_sources: list[str] = []

    def request_agents_refresh(self, source: str) -> None:
        self.refresh_sources.append(source)


def _override(
    limit: int = 4, *, expires_at: float | None = _NOW + 42 * 60
) -> TemporaryRunnerLimitOverride:
    return TemporaryRunnerLimitOverride(
        version=1,
        limit=limit,
        created_at=_NOW,
        expires_at=expires_at,
        source="test",
    )


def _snapshot(
    configured: int = 10,
    override: TemporaryRunnerLimitOverride | None = None,
) -> EffectiveRunnerLimitSnapshot:
    return EffectiveRunnerLimitSnapshot(
        configured_limit=configured,
        temporary_override=override,
        captured_at=_NOW,
    )


def _patch_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: EffectiveRunnerLimitSnapshot,
    *,
    use_chezmoi: bool = False,
) -> None:
    monkeypatch.setattr(models_panel, "_now", lambda: _NOW)
    monkeypatch.setattr(
        ModelsPanel,
        "_load_effective_runner_limit_snapshot",
        lambda self: (snapshot, use_chezmoi),
    )


@pytest.mark.parametrize("bucket_state", ["alias", "collapsed", "open"])
async def test_ctrl_r_opens_global_action_card_in_every_bucket_state(
    monkeypatch: pytest.MonkeyPatch, bucket_state: str
) -> None:
    patch_alias_views(monkeypatch, make_bucketed_views())
    _patch_snapshot(monkeypatch, _snapshot())

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        if bucket_state in {"collapsed", "open"}:
            await pilot.press("j", "j")
        if bucket_state == "open":
            await pilot.press("l")
        await pilot.press("ctrl+r")
        assert isinstance(pilot.app.screen, RunnerLimitActionModal)


async def test_title_footer_and_chooser_show_effective_and_configured_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("default", "default")])
    _patch_snapshot(monkeypatch, _snapshot(override=_override()))

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        title = panel.query_one("#models-panel-title", Static).content.plain
        assert title.endswith(
            "max running agents: 4  override · 42m left  configured 10"
        )
        footer = str(panel.query_one("#models-panel-footer", Static).content)
        assert "ctrl+e[/green]=Effort  [green]ctrl+r[/green]=Limit\n" in footer

        await pilot.press("ctrl+r")
        status = pilot.app.screen.query_one(
            "#runner-limit-action-status", Static
        ).content.plain
        assert "Current global-cap limit\n4 agents  override · 42m left" in status
        assert "Configured: 10 agents" in status
        assert len(pilot.app.screen.query(".runner-limit-action-row")) == 3
        note = pilot.app.screen.query_one("#runner-limit-action-note", Static).content
        assert "Already-running agents continue" in note
        assert "%wait(runners=N)" in note


async def test_chooser_hides_clear_and_describes_chezmoi() -> None:
    async with ModelsPanelTestApp().run_test() as pilot:
        pilot.app.push_screen(
            RunnerLimitActionModal(_snapshot(), now=_NOW, use_chezmoi=True)
        )
        await pilot.pause()
        assert len(pilot.app.screen.query(".runner-limit-action-row")) == 2
        assert (
            "chezmoi source"
            in pilot.app.screen.query_one(".runner-limit-action-row", Static).content
        )


@pytest.mark.parametrize(
    "raw",
    ["", "0", "-1", "+1", "1.5", " 1", "1 ", "True", "four"],
)
def test_value_parser_rejects_invalid_input(raw: str) -> None:
    with pytest.raises(ValueError):
        _parse_runner_limit(raw)


@pytest.mark.parametrize("raw, expected", [("1", 1), ("10", 10), ("0012", 12)])
def test_value_parser_accepts_unbounded_positive_decimal(
    raw: str, expected: int
) -> None:
    assert _parse_runner_limit(raw) == expected


async def test_value_card_retains_invalid_text_then_submits_valid_value() -> None:
    results: list[int | None] = []
    async with ModelsPanelTestApp().run_test() as pilot:
        pilot.app.push_screen(
            RunnerLimitValueModal("edit", initial=10), callback=results.append
        )
        await pilot.pause()
        value_input = pilot.app.screen.query_one("#runner-limit-value-input", Input)
        assert value_input.value == "10"
        value_input.value = "0"
        await pilot.press("enter")
        assert isinstance(pilot.app.screen, RunnerLimitValueModal)
        assert value_input.value == "0"
        assert (
            "at least 1"
            in pilot.app.screen.query_one("#runner-limit-value-error", Static).content
        )
        value_input.value = "12"
        await pilot.press("enter")
        await pilot.pause()
        assert results == [12]


async def test_edit_prefills_configured_and_override_prefills_effective(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("default", "default")])
    _patch_snapshot(monkeypatch, _snapshot(configured=10, override=_override(4)))

    async with ModelsPanelTestApp().run_test() as pilot:
        pilot.app.push_screen(ModelsPanel())
        await pilot.pause()
        await pilot.press("ctrl+r", "e")
        assert (
            pilot.app.screen.query_one("#runner-limit-value-input", Input).value == "10"
        )
        await pilot.press("escape", "ctrl+r", "o")
        assert (
            pilot.app.screen.query_one("#runner-limit-value-input", Input).value == "4"
        )


async def test_override_flow_reuses_duration_and_requests_agents_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_alias_views(
        monkeypatch,
        [
            make_alias_view("default", "default"),
            make_alias_view(
                "plain", "user", configured=True, configured_source="custom"
            ),
        ],
    )
    _patch_snapshot(monkeypatch, _snapshot())

    def set_override(
        self: ModelsPanel, limit: int, seconds: float | None
    ) -> TemporaryRunnerLimitOverride:
        assert limit == 4
        assert seconds == 15 * 60.0
        return _override(4, expires_at=_NOW + 15 * 60)

    monkeypatch.setattr(ModelsPanel, "_set_runner_limit_override", set_override)

    app = _RefreshingModelsPanelTestApp()
    async with app.run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        await pilot.press("j", "ctrl+r", "o")
        assert isinstance(pilot.app.screen, RunnerLimitValueModal)
        await pilot.press("4", "enter")
        assert isinstance(pilot.app.screen, DurationPickerModal)
        await pilot.press("1")
        for _ in range(20):
            await pilot.pause()
            if panel._runner_limit_override_worker is None:
                break
        assert panel._runner_limit_snapshot.effective_limit(_NOW) == 4
        assert panel._highlighted_row_id() == "plain"
        assert app.refresh_sources == ["models-runner-limit-override"]


async def test_clear_preserves_cursor_and_requests_agents_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_alias_views(
        monkeypatch,
        [
            make_alias_view("default", "default"),
            make_alias_view(
                "plain", "user", configured=True, configured_source="custom"
            ),
        ],
    )
    _patch_snapshot(monkeypatch, _snapshot(override=_override()))
    monkeypatch.setattr(ModelsPanel, "_clear_runner_limit_override", lambda self: True)

    app = _RefreshingModelsPanelTestApp()
    async with app.run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        await pilot.press("j", "ctrl+r", "x")
        for _ in range(20):
            await pilot.pause()
            if panel._runner_limit_clear_worker is None:
                break
        assert panel._runner_limit_snapshot.temporary_override is None
        assert panel._highlighted_row_id() == "plain"
        assert app.refresh_sources == ["models-runner-limit-clear"]


async def test_runner_cards_fit_narrow_supported_layout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("default", "default")])
    _patch_snapshot(monkeypatch, _snapshot(override=_override()))

    async with StyledModelsPanelTestApp().run_test(size=(80, 40)) as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        assert panel.region.right <= pilot.app.screen.size.width
        assert panel.region.bottom <= pilot.app.screen.size.height
        assert panel.query_one("#models-panel-footer", Static).region.bottom <= 40

        await pilot.press("ctrl+r")
        action_container = pilot.app.screen.query_one(
            "#runner-limit-action-container", Container
        )
        assert action_container.region.x >= 0
        assert action_container.region.right <= pilot.app.screen.size.width
        assert action_container.region.bottom <= pilot.app.screen.size.height

        await pilot.press("o")
        container = pilot.app.screen.query_one(
            "#runner-limit-value-container", Container
        )
        assert container.region.x >= 0
        assert container.region.right <= pilot.app.screen.size.width
        assert container.region.bottom <= pilot.app.screen.size.height


def test_persistent_edit_targets_user_base_and_preserves_yaml(
    tmp_path: Path,
) -> None:
    user_file = tmp_path / "sase.yml"
    user_file.write_text(
        "# top\nmax_running_agents: 10\n# keep me\nllm_provider: {}\n",
        encoding="utf-8",
    )
    layers = [
        ConfigLayer(
            name="default",
            path=None,
            exists=True,
            list_strategy="concatenate",
            data={"max_running_agents": 10},
        ),
        ConfigLayer(
            name="user",
            path=str(user_file),
            exists=True,
            list_strategy="replace",
            data={"max_running_agents": 10, "llm_provider": {}},
        ),
        ConfigLayer(
            name="local",
            path=str(tmp_path / "project" / "sase.yml"),
            exists=True,
            list_strategy="concatenate",
            data={"max_running_agents": 99},
        ),
    ]
    with patch("sase.config.inventory.load_config_layers", return_value=layers):
        plan = _plan_runner_limit_edit(1, use_chezmoi=False)
    assert plan.write_plan.layer == "user"
    assert plan.target_path == str(user_file)
    assert "# keep me" in plan.new_text
    assert "max_running_agents: 1" in plan.new_text
    assert plan.effective_preview.after == 99
    assert str(tmp_path / "project") not in (plan.target_path or "")


async def test_edit_preview_warns_when_temporary_override_remains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.models_panel_runner_limit_edit._plan_runner_limit_edit",
        lambda limit: make_edit_plan(value=limit),
    )
    async with ModelsPanelTestApp().run_test() as pilot:
        pilot.app.push_screen(RunnerLimitEditPreviewModal(4, override_active=True))
        await pilot.pause()
        preview = pilot.app.screen.query_one(
            "#alias-edit-preview", Static
        ).content.plain
        assert "max_running_agents" in preview
        assert "remains admission-effective until it expires or is cleared" in preview
