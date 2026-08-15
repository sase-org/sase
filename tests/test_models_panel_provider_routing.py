"""Models-panel provider-routing modal and title tests."""

from __future__ import annotations

from unittest.mock import MagicMock

from textual.widgets import OptionList, Static

import sase.ace.tui.modals.models_panel_providers as providers
from sase.ace.tui.modals.models_panel import ModelsPanel
from sase.ace.tui.modals.models_panel_duration import DurationPickerModal
from sase.ace.tui.modals.models_panel_providers import (
    _ProviderRoutingModal,
    _ProviderRoutingSnapshot,
    _provider_description_text,
    _render_provider_row,
)
from sase.llm_provider import ProviderRoutingStatus
from sase.llm_provider.provider_disable import (
    PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
    TemporaryProviderDisable,
)
from tests._models_panel_helpers import (
    ModelsPanelTestApp,
    make_alias_view,
    patch_alias_views,
    wait_for,
)


def _disable(
    provider: str,
    *,
    expires_at: float | None = None,
) -> TemporaryProviderDisable:
    return TemporaryProviderDisable(
        version=PROVIDER_DISABLE_WIRE_SCHEMA_VERSION,
        provider=provider,
        created_at=100.0,
        expires_at=expires_at,
        source="test",
    )


def _status(
    provider: str,
    *,
    model_count: int = 2,
    cli_available: bool = True,
    active_disable: TemporaryProviderDisable | None = None,
    hidden: bool = False,
    affected_aliases: tuple[str, ...] = ("default",),
) -> ProviderRoutingStatus:
    return ProviderRoutingStatus(
        provider=provider,
        model_count=model_count,
        cli_available=cli_available,
        active_disable=active_disable,
        hidden_from_model_pickers=hidden,
        affected_aliases=affected_aliases,
    )


def _snapshot(
    *statuses: ProviderRoutingStatus,
    disables: dict[str, TemporaryProviderDisable] | None = None,
) -> _ProviderRoutingSnapshot:
    return _ProviderRoutingSnapshot(
        statuses=tuple(statuses),
        provider_disables=disables or {},
        alias_views=(make_alias_view("default", "default"),),
        provider_colors={"claude": "#D97757", "codex": "#10A37F"},
        captured_at=100.0,
    )


def test_render_provider_rows_show_all_states() -> None:
    available = _render_provider_row(
        _status("codex", model_count=3),
        colors={"codex": "#10A37F"},
        now=100.0,
    )
    missing = _render_provider_row(
        _status("grok", model_count=1, cli_available=False),
        colors={},
        now=100.0,
    )
    disabled = _render_provider_row(
        _status("claude", active_disable=_disable("claude", expires_at=3_820.0)),
        colors={"claude": "#D97757"},
        now=100.0,
    )

    assert available.plain == "CODEX          3 models     available"
    assert missing.plain == "GROK           1 model      CLI missing"
    assert disabled.plain == "CLAUDE         2 models     disabled · 1h2m left"


def test_provider_description_lists_disabled_effect_and_aliases() -> None:
    description = _provider_description_text(
        _status(
            "claude",
            active_disable=_disable("claude", expires_at=None),
            affected_aliases=("large", "medium", "xlarge"),
        ),
        now=100.0,
    )

    assert "New launches and fallbacks route around CLAUDE" in description.plain
    assert "running provider processes continue" in description.plain
    assert "Affected aliases: @large, @medium, @xlarge." in description.plain


async def test_panel_p_opens_provider_routing_modal(monkeypatch) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("large", "role")])
    snapshot = _snapshot(_status("claude"), _status("codex"))
    monkeypatch.setattr(
        providers,
        "_load_provider_routing_snapshot",
        lambda _now=None: snapshot,
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()
        await pilot.press("p")
        await pilot.pause()

        assert isinstance(pilot.app.screen, _ProviderRoutingModal)


async def test_provider_modal_omits_hidden_provider_and_opens_duration() -> None:
    snapshot = _snapshot(
        _status("claude"),
        _status("fakey", hidden=True),
        _status("codex", cli_available=False),
    )

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = _ProviderRoutingModal(snapshot, load_snapshot=lambda: snapshot)
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#provider-routing-list", OptionList)
        ids = [str(option.id) for option in option_list.options]
        assert ids == ["claude", "codex"]

        await pilot.press("enter")
        await pilot.pause()

        assert isinstance(pilot.app.screen, DurationPickerModal)
        title = pilot.app.screen.query_one("#provider-duration-title", Static)
        assert title.content == "Disable CLAUDE"


async def test_provider_modal_disable_writes_and_refreshes_snapshot(
    monkeypatch,
) -> None:
    before = _snapshot(_status("claude"))
    disable = _disable("claude", expires_at=1_000.0)
    after = _snapshot(
        _status("claude", active_disable=disable),
        disables={"claude": disable},
    )
    load_snapshot = MagicMock(side_effect=[after, after])
    disable_mock = MagicMock(return_value=disable)
    monkeypatch.setattr(providers, "disable_provider", disable_mock)
    monkeypatch.setattr(providers, "_now", lambda: 100.0)
    snapshots: list[_ProviderRoutingSnapshot] = []

    async with ModelsPanelTestApp().run_test() as pilot:
        modal = _ProviderRoutingModal(
            before,
            load_snapshot=load_snapshot,
            on_snapshot=lambda snapshot, _provider: snapshots.append(snapshot),
        )
        modal.notify = MagicMock()  # type: ignore[method-assign]
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("1")
        await wait_for(pilot, lambda: modal._changed)

        disable_mock.assert_called_once_with(
            "claude",
            15 * 60.0,
            source="ace",
            now=100.0,
        )
        assert modal._changed is True
        assert snapshots[-1].provider_disables == {"claude": disable}
        modal.notify.assert_any_call(
            "CLAUDE disabled for 15m; alias routing refreshed."
        )


async def test_models_panel_title_shows_disabled_provider_line(monkeypatch) -> None:
    views = [make_alias_view("default", "default")]
    patch_alias_views(monkeypatch, views)
    disable = _disable("claude", expires_at=None)
    snapshot = _ProviderRoutingSnapshot(
        statuses=(_status("claude", active_disable=disable),),
        provider_disables={"claude": disable},
        alias_views=tuple(views),
        provider_colors={"claude": "#D97757"},
        captured_at=100.0,
    )
    monkeypatch.setattr(providers, "_now", lambda: 100.0)

    async with ModelsPanelTestApp().run_test() as pilot:
        panel = ModelsPanel()
        pilot.app.push_screen(panel)
        await pilot.pause()

        panel._apply_provider_snapshot(snapshot, keep="default")
        await pilot.pause()

        title = panel.query_one("#models-panel-title", Static).content.plain
        assert "disabled providers: CLAUDE until cleared" in title
