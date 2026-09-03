"""Widget-level tests for the merged Updates list and scope filter."""

from __future__ import annotations

import pytest
from textual.widgets import OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_center_session import AdminCenterSessionState
from sase.ace.tui.modals.plugins_browser_pane import PluginsBrowserPane
from sase.ace.tui.modals.plugins_browser_rows import SCOPE_LABELS, SCOPE_ORDER
from sase.ace.tui.widgets.panel_tab_strip import PanelTabStrip
from sase.plugins.catalog import PluginCatalog
from tests.ace.tui._plugins_browser_pane_helpers import (
    _NOW,
    _agent_cli_statuses,
    _catalog,
    _entry,
    _highlight_row,
    _not_uv_tool,
    _open_plugins_pane,
    _option_labels,
    _patch_catalog,
    _patch_other_panes,
    _uv_tool,
)


def _option_ids(pane: PluginsBrowserPane) -> list[str]:
    option_list = pane.query_one("#updates-list", OptionList)
    return [
        str(option_list.get_option_at_index(index).id)
        for index in range(option_list.option_count)
        if option_list.get_option_at_index(index).id is not None
    ]


async def test_merged_list_shows_every_kind_once_under_section_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
        uv_tool=_uv_tool(),
    )
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        labels = _option_labels(pane)
        headers = [label for label in labels if label.startswith("──")]
        assert headers == [
            "── SASE ──",
            "── Plugins · Built-in ──",
            "── Plugins · Community ──",
            "── Agent CLIs ──",
        ]
        ids = [
            option_id
            for option_id in _option_ids(pane)
            if option_id.startswith("updates-row__")
        ]
        assert ids.count("updates-row__core:sase") == 1
        assert ids.count("updates-row__plugin:github") == 1
        assert ids.count("updates-row__cli:claude") == 1
        assert len(ids) == len(set(ids))


async def test_scope_membership_includes_manual_cli_error_and_excludes_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
        uv_tool=_uv_tool(),
    )
    async with AcePage() as page:
        pane = await _open_plugins_pane(page, scope="outdated")
        ids = _option_ids(pane)
        assert "updates-row__cli:codex" in ids
        assert "updates-row__plugin:nvim" not in ids

        pane._set_scope("installed")
        ids = _option_ids(pane)
        assert "updates-row__plugin:nvim" not in ids
        assert "updates-row__plugin:github" in ids

        pane._set_scope("all")
        ids = _option_ids(pane)
        assert "updates-row__plugin:nvim" in ids


async def test_one_filter_matches_core_plugin_and_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    plugin = _entry("github", owner="sase-org", topics=("needle-dist", "sase--plugin"))
    catalog = PluginCatalog(
        fetched_at=_NOW, entries=(plugin,), from_cache=True, stale=False
    )
    from sase.agent_clis.models import AgentCliStatus, InstallMethod
    from sase.uv_tool.versions import CorePackageVersion, CoreVersions

    core = CoreVersions(
        packages=(
            CorePackageVersion(
                name="sase",
                distribution_name="needle-dist",
                installed_version="1.0.0",
                latest_version="1.0.0",
                latest_checked=True,
                update_available=False,
            ),
        )
    )
    cli = AgentCliStatus(
        name="claude",
        display_name="Claude Code",
        binary="needle-dist",
        executable="/bin/claude",
        installed_version="1.0.0",
        latest_version="1.0.0",
        install_method=InstallMethod.SELF_MANAGED,
        update_available=False,
        docs_url=None,
        install_hint="install",
        self_update_argv=("update",),
    )
    _patch_catalog(
        monkeypatch,
        catalog=catalog,
        core_versions=core,
        agent_cli_statuses=(cli,),
        uv_tool=_uv_tool(),
    )
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane._filter_text = "needle-dist"
        pane._apply_filter()
        keys = [row.key for _header, _style, rows in pane._grouped for row in rows]
        assert keys == ["core:sase", "plugin:github", "cli:claude"]


async def test_cursor_survives_refresh_filter_and_scope_by_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
        uv_tool=_uv_tool(),
    )
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        _highlight_row(pane, "plugin:telegram")
        pane._record_bookmark("plugin:telegram")
        pane.action_refresh()
        await page.wait_for(lambda _s: not pane._loading)
        assert pane._session_state.rows.identity == "plugin:telegram"

        pane._filter_text = "telegram"
        pane._apply_filter()
        assert pane._session_state.rows.identity == "plugin:telegram"

        pane._filter_text = ""
        pane._apply_filter()
        pane._set_scope("installed")
        assert pane._session_state.rows.identity == "plugin:telegram"
        pane._set_scope("all")
        option_list = pane.query_one("#updates-list", OptionList)
        highlighted = option_list.get_option_at_index(option_list.highlighted)
        assert highlighted.id == "updates-row__plugin:telegram"


async def test_empty_identity_open_lands_on_first_outdated_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
        uv_tool=_uv_tool(),
    )
    state = AdminCenterSessionState()
    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="updates", session_state=state)
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#updates")))
        pane = modal.query_one("#updates", PluginsBrowserPane)
        await page.wait_for(lambda _s: not pane._loading)
        option_list = pane.query_one("#updates-list", OptionList)
        highlighted = option_list.get_option_at_index(option_list.highlighted)
        assert highlighted.id == "updates-row__plugin:github"


async def test_check_action_follows_highlighted_row_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
        uv_tool=_uv_tool(),
    )
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        _highlight_row(pane, "plugin:github")
        assert pane.check_action("update", ()) is True
        assert pane.check_action("uninstall", ()) is True
        assert pane.check_action("toggle_install_mark", ()) is False
        assert pane.check_action("toggle_history_scope", ()) is False

        _highlight_row(pane, "plugin:nvim")
        assert pane.check_action("toggle_install_mark", ()) is True
        assert pane.check_action("update", ()) is False
        assert pane.check_action("uninstall", ()) is False

        _highlight_row(pane, "cli:claude")
        assert pane.check_action("toggle_history_scope", ()) is True
        assert pane.check_action("uninstall", ()) is False

        _highlight_row(pane, "core:sase")
        assert pane.check_action("update", ()) is False
        assert pane.check_action("uninstall", ()) is False
        assert pane.check_action("toggle_history_scope", ()) is False


async def test_check_action_withdraws_plugin_verbs_when_not_uv_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        uv_tool=_not_uv_tool(),
    )
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        _highlight_row(pane, "plugin:nvim")
        assert pane.check_action("install", ()) is False
        assert pane.check_action("toggle_install_mark", ()) is False
        _highlight_row(pane, "plugin:github")
        assert pane.check_action("update", ()) is False
        assert pane.check_action("uninstall", ()) is False


async def test_install_mark_survives_scope_switch_away_from_available_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog(), uv_tool=_uv_tool())
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        _highlight_row(pane, "plugin:nvim")
        pane.action_toggle_install_mark()
        assert "nvim" in pane._marked_install
        pane._set_scope("installed")
        assert "nvim" in pane._marked_install
        pane._set_scope("all")
        assert "nvim" in pane._marked_install
        option_list = pane.query_one("#updates-list", OptionList)
        nvim_index = pane._row_option_index["plugin:nvim"]
        prompt = option_list.get_option_at_index(nvim_index).prompt
        assert "[✓]" in (prompt.plain if hasattr(prompt, "plain") else str(prompt))


async def test_scope_strip_counts_and_tab_click_select_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        agent_cli_statuses=_agent_cli_statuses(),
        uv_tool=_uv_tool(),
    )
    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        strip = pane.query_one("#updates-scopes", PanelTabStrip)
        labels = strip.render().plain
        folded = labels.casefold()
        for scope in SCOPE_ORDER:
            assert SCOPE_LABELS[scope].casefold() in folded
        assert "9" in labels
        pane._on_scope_clicked(PanelTabStrip.TabClicked("outdated"))
        assert pane._scope == "outdated"
        assert pane._session_state.scope == "outdated"
