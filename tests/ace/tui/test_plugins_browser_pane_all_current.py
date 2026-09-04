"""All-current Updates pane banner and action-gating tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from sase.agent_clis.models import AgentCliStatus, InstallMethod
from sase.ace.testing import AcePage
from sase.ace.tui.modals.plugins_browser_rows import SCOPE_ORDER
from sase.agents_sync.models import (
    CapturedIncomingHood,
    ProjectSyncStatus,
    SyncStatusSnapshot,
)
from sase.plugins.latest import LatestInfo
from tests.ace.tui._plugins_browser_pane_helpers import (
    _NOW,
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


def _captured_hood(machine: str, hood: str) -> CapturedIncomingHood:
    return CapturedIncomingHood(
        project_key="sase",
        project="SASE",
        fetched_ref="refs/remotes/origin/main",
        fetched_sha="a" * 40,
        cache_id=f"{machine}-{hood}",
        format_version=2,
        source_owner_kind="exact",
        source_username="alice",
        source_machine=machine,
        top_hood=hood,
        hood_digest="b" * 64,
        run_count=1,
        family_count=1,
        cache_created_at=1.0,
    )


def _agents_snapshot(*machines: str) -> SyncStatusSnapshot:
    return SyncStatusSnapshot(
        checked_at=_NOW,
        projects=(
            ProjectSyncStatus(
                project_key="sase",
                project="SASE",
                state="ready",
                pending_updates=tuple(
                    _captured_hood(machine, machine) for machine in machines
                ),
            ),
        ),
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

        text = _render(pane._header_renderable())
        assert "You're all up to date" not in text
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
    _patch_catalog(
        monkeypatch,
        catalog=_all_current_catalog(),
        uv_tool=_uv_tool(),
        install_mode="dev",
    )

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)
        pane.action_toggle_offline()
        await page.wait_for(lambda _s: pane._offline and not pane._loading)

        text = _render(pane._header_renderable())
        assert "You're all up to date" not in text
        assert "checked just now" in text
        assert "Dev (editable)" in text
        assert "OFFLINE" in text


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

        text = _render(pane._header_renderable())
        assert "You're all up to date" not in text
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

        text = _render(pane._header_renderable())
        assert "You're all up to date" not in text
        assert "SASE: latest probe failed for 2 rows (sase: unavailable)" in text
        assert pane.check_action("update_sase", ()) is True
        assert "u update" in pane._hints()


async def test_updates_pane_failed_core_probe_suppresses_all_current_banner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_all_current_catalog(),
        uv_tool=_uv_tool(),
        core_versions=_core_versions(),
        core_error="PyPI probe failed",
    )

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)

        text = _render(pane._header_renderable())
        assert pane._core_error == "PyPI probe failed"
        assert "You're all up to date" not in text
        assert "SASE: PyPI probe failed" in text


async def test_updates_pane_all_current_banner_hidden_when_plugin_latest_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    catalog = _all_current_catalog()
    entries = tuple(
        replace(entry, latest=LatestInfo.unknown()) if entry.name == "github" else entry
        for entry in catalog.entries
    )
    _patch_catalog(
        monkeypatch,
        catalog=replace(catalog, entries=entries),
        uv_tool=_uv_tool(),
    )

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)

        text = _render(pane._header_renderable())
        assert "You're all up to date" not in text
        assert "Plugins: latest version unknown for github" in text


async def test_updates_pane_digest_counts_match_row_domains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(
        monkeypatch,
        catalog=_catalog(),
        uv_tool=_uv_tool(),
        core_versions=_core_versions(sase_latest="0.6.0"),
        agent_cli_statuses=(
            replace(
                _current_agent_cli(),
                latest_version="1.1.0",
                update_available=True,
            ),
            replace(
                _current_agent_cli(),
                name="codex",
                display_name="Codex CLI",
                binary="codex",
                executable="/bin/codex",
                installed_version="1.0.0",
                latest_version="1.1.0",
                update_available=True,
            ),
        ),
    )

    async with AcePage() as page:
        pane = await _open_plugins_pane(page)

        text = _render(pane._header_renderable())
        assert "↑ 4 updates" in text
        assert "sase 0.5.0 → 0.6.0" in text
        assert "1 plugin" in text
        assert "2 agent CLIs" in text


async def test_updates_pane_agents_sync_chip_uses_cached_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog(), uv_tool=_uv_tool())

    async with AcePage() as page:
        page.app._agents_sync_last_status = _agents_snapshot("athena", "zeus")
        pane = await _open_plugins_pane(page)

        text = _render(pane._header_renderable())
        assert "⇅ 2 hoods" in text
        assert "athena, zeus" in text


async def test_updates_pane_agents_sync_chip_omitted_at_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog(), uv_tool=_uv_tool())

    async with AcePage() as page:
        page.app._agents_sync_last_status = SyncStatusSnapshot(_NOW)
        pane = await _open_plugins_pane(page)

        assert "⇅" not in _render(pane._header_renderable())
