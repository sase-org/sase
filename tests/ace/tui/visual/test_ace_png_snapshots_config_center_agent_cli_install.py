"""sase's TUI PNG visual snapshots for agent-CLI installs in the Updates tab."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.agent_clis.install import (
    AgentCliInstallEntry,
    AgentCliInstallsPlanned,
    InstallScript,
)
from sase.agent_clis.models import InstallRoute
from tests.ace.tui._plugins_browser_pane_helpers import (
    _agent_cli_statuses,
    _highlight_row,
    _ready_many_plan,
)
from tests.ace.tui.visual._ace_config_center_png_snapshot_helpers import (
    _build_view,
    _config_layers,
    _config_schema,
    _open_plugins_modal,
    _patch_config_view,
    _patch_plugins_catalog,
    _patch_xprompt_sources,
    _wait_for_plugins_detail,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_FIXED_DIGEST = "0123456789abcdef" * 4


def _stub_install_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub install planning with a fixed digest and ``/home/visual`` paths."""
    statuses = {status.name: status for status in _agent_cli_statuses()}
    script = InstallScript(
        url="https://dev.meta.ai/install.sh",
        path=Path("/home/visual/.cache/sase/agent-clis/install-01234567.sh"),
        digest=_FIXED_DIGEST,
        size_bytes=48213,
    )
    plan = AgentCliInstallsPlanned(
        entries=(
            AgentCliInstallEntry(
                statuses["qwen"],
                route=InstallRoute.NPM,
                argv=("npm", "install", "-g", "@qwen-code/qwen-code"),
                env_overlay=(),
                install_dir="/home/visual/.npm-global/bin",
                install_dir_on_path=True,
            ),
            AgentCliInstallEntry(
                statuses["muse"],
                route=InstallRoute.SCRIPT,
                argv=("bash", str(script.path)),
                env_overlay=(),
                script=script,
                install_dir="/home/visual/.local/bin",
                install_dir_on_path=False,
            ),
            AgentCliInstallEntry(
                statuses["antigravity"],
                route=InstallRoute.MANUAL,
                skip_reason=(
                    "no SASE-runnable installer — see https://antigravity.dev/download"
                ),
            ),
        )
    )
    monkeypatch.setattr(pbp, "_plan_agent_cli_installs", lambda names, **_kwargs: plan)


async def test_config_center_agent_cli_install_detail_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing npm CLI rows render the install detail panel and CTA."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_plugins_modal(page)
        _highlight_row(pane, "cli:qwen")
        pane._render_detail_now(force=True)
        await page.wait_for(lambda _s: pane._detail_key == "cli:qwen")
        await _wait_for_plugins_detail(page, pane)

        ace_png_visual.assert_page_png(
            page,
            "config_center_agent_cli_install_detail_120x40",
            title="ACE SASE Admin Center — Agent CLI install detail",
        )


async def test_config_center_agent_cli_install_preview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Install confirmation previews npm + script sections with digest and skips."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(monkeypatch)
    _stub_install_plan(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_plugins_modal(page)
        _highlight_row(pane, "cli:qwen")
        pane.action_install()
        await page.expect_modal("PluginActionConfirmModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_agent_cli_install_preview_120x40",
            title="ACE SASE Admin Center — Agent CLI install preview",
        )


async def test_config_center_agent_cli_install_marked_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Marked CLI installs render checkmarks plus the aggregate marked line."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_plugins_modal(page)
        _highlight_row(pane, "cli:qwen")
        pane.action_toggle_mark()
        _highlight_row(pane, "cli:muse")
        pane.action_toggle_mark()
        await _wait_for_plugins_detail(page, pane)

        ace_png_visual.assert_page_png(
            page,
            "config_center_agent_cli_install_marked_120x40",
            title="ACE SASE Admin Center — Marked agent CLI installs",
        )


async def test_config_center_updates_available_scope_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Available scope lists only not-installed rows with live counts."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_plugins_modal(page, scope="available")
        await _wait_for_plugins_detail(page, pane)

        ace_png_visual.assert_page_png(
            page,
            "config_center_updates_available_scope_120x40",
            title="ACE SASE Admin Center — Updates tab (Available scope)",
        )


async def test_config_center_updates_mark_all_clis_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`*` marks every visible Agent CLI install with the aggregate line."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_plugins_modal(page)
        _highlight_row(pane, "cli:qwen")
        pane.action_toggle_mark_all()
        await _wait_for_plugins_detail(page, pane)

        ace_png_visual.assert_page_png(
            page,
            "config_center_updates_mark_all_clis_120x40",
            title="ACE SASE Admin Center — Updates tab (mark all agent CLIs)",
        )


async def test_config_center_agent_cli_install_mixed_preview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mixed marked set previews agent-CLI sections plus a Plugins section."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(monkeypatch)
    _stub_install_plan(monkeypatch)
    plugin_plan = _ready_many_plan(("nvim",))
    monkeypatch.setattr(
        pbp,
        "_plan_install_many_preview",
        lambda names, **_kwargs: pbp._InstallManyPreview(plan=plugin_plan),
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_plugins_modal(page)
        _highlight_row(pane, "cli:qwen")
        pane.action_toggle_mark()
        for _key in ("plugin:nvim",):
            _highlight_row(pane, _key)
            pane.action_toggle_mark()
        pane.action_install()
        await page.expect_modal("PluginActionConfirmModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_agent_cli_install_mixed_preview_120x40",
            title="ACE SASE Admin Center — Mixed plugin + agent CLI install preview",
        )
