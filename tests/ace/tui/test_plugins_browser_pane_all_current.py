"""All-current Updates pane banner and action-gating tests."""

from __future__ import annotations

import pytest

from sase.agent_clis.models import AgentCliStatus, InstallMethod
from sase.ace.testing import AcePage
from sase.ace.tui.modals.plugins_browser_rows import SCOPE_ORDER
from tests.ace.tui._plugins_browser_pane_helpers import (
    _all_current_catalog,
    _catalog,
    _core_versions,
    _not_uv_tool,
    _open_plugins_pane,
    _patch_catalog,
    _patch_other_panes,
    _render,
    _uv_tool,
)


def _current_agent_cli() -> AgentCliStatus:
    return AgentCliStatus(
        name="claude",
        display_name="Claude Code",
        binary="claude",
        executable="/bin/claude",
        installed_version="1.0.0",
        latest_version="1.0.0",
        install_method=InstallMethod.SELF_MANAGED,
        update_available=False,
        docs_url="https://example.test/claude",
        install_hint="install claude",
        self_update_argv=("update",),
    )


async def test_updates_pane_all_current_banner_shown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_all_current_catalog(), uv_tool=_uv_tool())

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        for scope in SCOPE_ORDER:
            pane._set_scope(scope)
            text = _render(pane._header_renderable())
            assert "You're all up to date" in text
        text = _render(pane._all_current_banner())
        assert "sase v0.5.0 · sase-core v1.4.2 · 2 plugins current" in text
        assert "0 agent CLIs current" in text
        assert "Last checked just now · press r to re-check" in text
        assert pane.check_action("update_sase", ()) is False
        assert "u update" not in pane._hints()


async def test_updates_pane_all_current_banner_includes_checked_agent_clis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_all_current_catalog(),
        uv_tool=_uv_tool(),
        agent_cli_statuses=(_current_agent_cli(),),
    )

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)

        assert "You're all up to date" in _render(pane._header_renderable())
        assert "1 agent CLI current" in _render(pane._all_current_banner())


async def test_updates_pane_all_current_banner_hides_unknown_agent_cli_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_all_current_catalog(),
        uv_tool=_uv_tool(),
        agent_cli_statuses=(_current_agent_cli(),),
        agent_cli_error="registry unavailable",
    )

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)

        assert "You're all up to date" not in _render(pane._header_renderable())


async def test_updates_pane_update_action_available_when_updates_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)

        assert "You're all up to date" not in _render(pane._header_renderable())
        assert pane.check_action("update_sase", ()) is True
        assert "u update" in pane._hints()


async def test_updates_pane_all_current_banner_hidden_while_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_all_current_catalog(), uv_tool=_uv_tool())

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane._loading = True
        pane._sync_header()

        assert "You're all up to date" not in _render(pane._header_renderable())


async def test_updates_pane_all_current_banner_hidden_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_all_current_catalog(),
        error="boom",
        uv_tool=_uv_tool(),
    )

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)

        assert pane._error == "boom"
        assert "You're all up to date" not in _render(pane._header_renderable())


async def test_updates_pane_all_current_banner_hidden_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_all_current_catalog(), uv_tool=_uv_tool())

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane.action_toggle_offline()
        await page.wait_for(lambda _s: pane._offline and not pane._loading)

        assert "You're all up to date" not in _render(pane._header_renderable())


async def test_updates_pane_all_current_banner_hidden_when_not_uv_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_all_current_catalog(),
        uv_tool=_not_uv_tool(),
    )

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)

        assert "You're all up to date" not in _render(pane._header_renderable())
        assert pane.check_action("update_sase", ()) is False
        assert "u update" not in pane._hints()


async def test_updates_pane_all_current_banner_hidden_when_core_latest_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_all_current_catalog(),
        uv_tool=_uv_tool(),
        core_versions=_core_versions(sase_latest=None, latest_error="unavailable"),
    )

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)

        assert "You're all up to date" not in _render(pane._header_renderable())
        assert pane.check_action("update_sase", ()) is True
        assert "u update" in pane._hints()
