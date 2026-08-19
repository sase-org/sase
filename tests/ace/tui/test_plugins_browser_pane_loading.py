"""Load, grouping, filtering, and tab-cycle tests for the Plugins pane."""

from __future__ import annotations

import threading

import pytest
from textual.widgets import Input, OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.actions import update_toast
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_center_session import AdminCenterSessionState
from sase.plugins.catalog import PluginCatalog
from sase.ace.tui.widgets import UpdatesAvailableIndicator
from sase.updates import build_update_status
from sase.updates.incoming_commits import CommitSummary, IncomingCommits
from tests.ace.tui._plugins_browser_pane_helpers import (
    _NOW,
    _catalog,
    _core_versions,
    _not_uv_tool,
    _open_plugins_pane,
    _option_labels,
    _patch_catalog,
    _patch_other_panes,
    _render,
)


async def test_plugins_pane_loads_and_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        # Both section headers and every plugin row are present.
        labels = _option_labels(pane)
        assert any("Built-in" in label for label in labels)
        assert any("Community" in label for label in labels)
        assert any("github" in label for label in labels)
        assert any("acme" in label for label in labels)
        # The status placeholder is hidden and the list is visible.
        assert pane.query_one("#plugins-list").display is True
        assert pane.query_one("#plugins-status").display is False
        # A non-header row is auto-highlighted.
        option_list = pane.query_one("#plugins-list", OptionList)
        assert option_list.highlighted is not None
        highlighted = option_list.get_option_at_index(option_list.highlighted)
        assert highlighted.id is not None
        assert not str(highlighted.id).startswith("__header__")


async def test_plugins_session_restores_plugin_by_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    state = AdminCenterSessionState()
    state.updates.active_subtab = "plugins"
    state.updates.plugins.record("telegram", 0)

    async with AcePage() as page:
        pane = await _open_plugins_pane(page, session_state=state)
        option_list = pane.query_one("#plugins-list", OptionList)
        assert option_list.highlighted is not None
        highlighted = option_list.get_option_at_index(option_list.highlighted)

        assert highlighted.id == "plugin__telegram"
        assert state.updates.plugins.identity == "telegram"
        assert state.updates.active_subtab == "plugins"


async def test_plugins_pane_summary_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        summary = pane._summary_text()
        assert "4 plugins" in summary
        assert "2 installed" in summary
        assert "1 updates available" in summary
        assert "just now" in summary


async def test_panel_fresh_compute_grows_badge_and_signals_core_rebuild(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    versions = _core_versions(sase_latest="0.6.0", core_latest="1.5.0")
    catalog = _catalog()
    status = build_update_status(versions, catalog, now=_NOW)
    _patch_catalog(
        monkeypatch,
        catalog=catalog,
        core_versions=versions,
        update_status=status,
    )
    monkeypatch.setattr(
        update_toast,
        "_load_update_toast_config",
        lambda: update_toast._UpdateToastConfig(startup_toast=False),
    )
    monkeypatch.setattr(
        update_toast,
        "revalidate_update_status",
        lambda loaded: loaded,
    )
    monkeypatch.setattr(
        update_toast,
        "get_cached_update_status",
        lambda **_kwargs: None,
    )

    async with AcePage() as page:
        indicator = page.app.query_one(
            "#updates-indicator",
            UpdatesAvailableIndicator,
        )
        indicator.set_available(1)

        await _open_plugins_pane(page)
        await page.wait_for(lambda _state: indicator.count == 3)

        assert indicator.core is True


async def test_updates_pane_core_panel_shows_versions_and_update_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane._core_versions = _core_versions(sase_latest="0.6.0")
        rendered = pane._core_versions_panel()

        text = str(_render(rendered))
        assert "SASE Core" in text
        assert "sase" in text
        assert "v0.5.0" in text
        assert "v0.6.0" in text
        assert "update available" in text
        assert "u  run `sase update`" in text


async def test_updates_pane_core_panel_shows_incoming_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    versions = _core_versions(sase_latest="0.6.0")
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        core_versions=versions,
        core_incoming_commits={
            "sase": IncomingCommits(
                total=2,
                commits=(
                    CommitSummary("abc1234", "Newest core change"),
                    CommitSummary("def5678", "Older core change"),
                ),
                source="github",
            )
        },
    )
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        text = str(_render(pane._core_versions_panel()))

        assert "sase" in text
        assert "↑ 2 incoming commits" in text
        assert "Newest core change" in text


async def test_updates_pane_core_panel_drops_cta_when_not_uv_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane._uv_tool = _not_uv_tool()
        text = str(_render(pane._core_versions_panel()))

        assert "`sase update` unavailable" in text
        assert "run `sase update`" not in text
        assert "u update" not in pane._hints()


async def test_plugins_pane_shows_update_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        labels = _option_labels(pane)
        github_row = next(label for label in labels if "github" in label)
        # Installed with an available update: version arrow + update glyph.
        assert "v1.2.0 → v1.3.0" in github_row
        assert "↑" in github_row
        nvim_row = next(label for label in labels if "nvim" in label)
        assert "latest v2.0.0" in nvim_row


async def test_plugins_pane_filter_narrows_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane.action_focus_filter()
        await page.pause()
        await page.press("g", "i", "t", "h", "u", "b")
        await page.wait_for(
            lambda _s: (
                [e.name for _, _, e_list in pane._grouped for e in e_list] == ["github"]
            )
        )
        labels = _option_labels(pane)
        assert any("github" in label for label in labels)
        assert not any("telegram" in label for label in labels)
        # Cancelling restores the full list.
        pane.cancel_input()
        await page.wait_for(
            lambda _s: any(
                e.name == "telegram" for _, _, lst in pane._grouped for e in lst
            )
        )


async def test_updates_filter_forwards_brackets_and_tab_switches_main_tab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        modal = page.app.screen
        assert isinstance(modal, ConfigCenterModal)
        pane.action_focus_filter()
        filter_input = pane.query_one("#plugins-filter-input", Input)
        await page.wait_for(lambda _s: filter_input.has_focus)

        await page.press("left_square_bracket")
        await page.wait_for(lambda _s: pane._active_subtab == "core")
        assert filter_input.value == ""
        assert modal._active_tab == "updates"

        pane._switch_to_subtab("plugins")
        await page.press("tab")
        await page.wait_for(lambda _s: modal._active_tab == "xprompts")
        assert filter_input.value == ""
        assert page.app.current_tab == "artifacts"


async def test_plugins_pane_filter_no_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane.action_focus_filter()
        await page.pause()
        await page.press("z", "z", "z", "z")
        await page.wait_for(lambda _s: not pane._grouped)
        assert pane.query_one("#plugins-status").display is True
        assert "No plugins match" in pane._status_message()


async def test_plugins_pane_empty_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    empty = PluginCatalog(fetched_at=_NOW, entries=(), from_cache=True, stale=False)
    _patch_catalog(monkeypatch, catalog=empty)
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        assert pane.query_one("#plugins-status").display is True
        assert pane.query_one("#plugins-list").display is False
        assert "No SASE plugins found." in pane._status_message()


async def test_plugins_pane_error_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=None, error="gh not found")
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        assert pane._error == "gh not found"
        assert pane.query_one("#plugins-status").display is True
        assert "gh not found" in pane._status_message()


async def test_updates_pane_manual_update_reuses_load_freshness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    fresh_roots = frozenset({"/repo/sase"})
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        fresh_editable_roots=fresh_roots,
    )
    planned_with: list[frozenset[str]] = []

    def _preview(
        _receipt: object | None,
        *,
        already_refreshed_roots: frozenset[str] = frozenset(),
    ) -> pbp._DevUpdatePreview:
        planned_with.append(frozenset(already_refreshed_roots))
        return pbp._DevUpdatePreview(plan=None, subject="sase")

    monkeypatch.setattr(pbp, "_make_sase_dev_update_preview", _preview)

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane.action_update_sase()
        await page.expect_modal("PluginActionConfirmModal")

        assert planned_with == [fresh_roots]


async def test_updates_pane_manual_update_drops_expired_load_freshness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    fresh_roots = frozenset({"/repo/sase"})
    clock = [100.0]
    monkeypatch.setattr(pbp, "_monotonic", lambda: clock[0])
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        fresh_editable_roots=fresh_roots,
    )
    planned_with: list[frozenset[str]] = []

    def _preview(
        _receipt: object | None,
        *,
        already_refreshed_roots: frozenset[str] = frozenset(),
    ) -> pbp._DevUpdatePreview:
        planned_with.append(frozenset(already_refreshed_roots))
        return pbp._DevUpdatePreview(plan=None, subject="sase")

    monkeypatch.setattr(pbp, "_make_sase_dev_update_preview", _preview)

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        assert (
            pane._reusable_fresh_editable_roots(
                now=100.0 + pbp._FRESH_EDITABLE_ROOTS_TTL_SECONDS
            )
            == fresh_roots
        )

        clock[0] += pbp._FRESH_EDITABLE_ROOTS_TTL_SECONDS + 0.001
        pane.action_update_sase()
        await page.expect_modal("PluginActionConfirmModal")

        assert planned_with == [frozenset()]


async def test_updates_pane_reload_clears_freshness_while_in_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    fresh_roots = frozenset({"/repo/sase"})
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        fresh_editable_roots=fresh_roots,
    )

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        assert pane._reusable_fresh_editable_roots() == fresh_roots
        loaded = pbp._load_plugins_catalog
        release = threading.Event()

        def _blocked_reload(**kwargs: object) -> pbp._PluginsLoadResult:
            release.wait(timeout=5.0)
            return loaded(**kwargs)

        monkeypatch.setattr(pbp, "_load_plugins_catalog", _blocked_reload)
        pane.action_refresh()

        assert pane._loading is True
        assert pane._reusable_fresh_editable_roots() == frozenset()

        release.set()
        await page.wait_for(lambda _s: not pane._loading)
        assert pane._reusable_fresh_editable_roots() == fresh_roots


async def test_updates_pane_offline_reload_does_not_retain_freshness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    fresh_roots = frozenset({"/repo/sase"})
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        fresh_editable_roots=fresh_roots,
    )

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        assert pane._reusable_fresh_editable_roots() == fresh_roots

        pane.action_toggle_offline()
        await page.wait_for(lambda _s: pane._offline and not pane._loading)

        assert pane._reusable_fresh_editable_roots() == frozenset()


async def test_config_center_cycles_seven_tabs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="config")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _state: modal._active_tab == "config")
        # Tabs cycle alphabetically by their visible labels.
        for tab in (
            "logs",
            "procs",
            "projects",
            "statistics",
            "updates",
            "xprompts",
            "config",
        ):
            modal.action_next_center_tab()
            await page.wait_for(
                lambda _state, expected=tab: modal._active_tab == expected
            )
        # Wrapping backwards lands on the rightmost XPrompts tab.
        modal.action_prev_center_tab()
        await page.wait_for(lambda _state: modal._active_tab == "xprompts")
