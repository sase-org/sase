"""ACE TUI PNG snapshots for the Launch Control tmux Agent modal."""

from __future__ import annotations

from collections.abc import Sequence
import subprocess

import pytest

from sase.ace.testing import AcePage
import sase.ace.tui.modals.tmux_agent_modal as tmux_agent_modal
from sase.ace.tui.modals.tmux_agent_modal import TmuxAgentModal
from sase.config.tmux_agent import TmuxAgentConfig
from sase.llm_provider import TemporaryProviderDisable
from sase.tmux_agent import TmuxAgentCatalog, TmuxAgentEntry, TmuxRunner
from tests.ace.tui.visual._ace_models_panel_png_snapshot_fixtures import (
    FROZEN_NOW,
    provider_disable,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _tmux_agent_entry(
    provider: str,
    *,
    key: str,
    display_name: str,
    vendor: str,
    color: str,
    installed: bool = True,
    argv: tuple[str, ...] = (),
    routing_disabled: TemporaryProviderDisable | None = None,
    install_hint: str = "",
    bypass: bool = True,
) -> TmuxAgentEntry:
    return TmuxAgentEntry(
        provider=provider,
        display_name=display_name,
        vendor=vendor,
        color=color,
        key=key,
        binary=provider,
        executable=f"/usr/bin/{provider}" if installed else None,
        installed=installed,
        install_hint=install_hint or f"install {provider} first",
        routing_disabled=routing_disabled,
        argv=argv or (provider,),
        env=(),
        effort=None,
        effort_skipped=None,
        bypass=bypass,
    )


def _tmux_agent_runner() -> TmuxRunner:
    def run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        argv = [str(item) for item in args]
        return subprocess.CompletedProcess(argv, 0, "", "")

    return TmuxRunner(run=run)


async def test_models_panel_tmux_agent_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(tmux_agent_modal, "_wall_clock_now", lambda: FROZEN_NOW)
    disable = provider_disable("grok", expires_at=FROZEN_NOW + 2_520.0)
    catalog = TmuxAgentCatalog(
        entries=(
            _tmux_agent_entry(
                "agy",
                key="a",
                display_name="Antigravity CLI",
                vendor="Antigravity",
                color="#6E5DE7",
                argv=("agy", "--dangerously-skip-permissions"),
            ),
            _tmux_agent_entry(
                "claude",
                key="c",
                display_name="Claude Code",
                vendor="Anthropic",
                color="#D97757",
                argv=("claude", "--dangerously-skip-permissions", "--effort", "max"),
            ),
            _tmux_agent_entry(
                "grok",
                key="g",
                display_name="Grok Build",
                vendor="xAI",
                color="#00C8D7",
                routing_disabled=disable,
                argv=("grok", "--always-approve"),
            ),
            _tmux_agent_entry(
                "qwen",
                key="q",
                display_name="Qwen Code",
                vendor="Alibaba",
                color="#D75FFF",
                installed=False,
                install_hint="npm install -g @qwen-code/qwen-code",
            ),
            _tmux_agent_entry(
                "codex",
                key="x",
                display_name="Codex CLI",
                vendor="OpenAI",
                color="#10A37F",
                argv=(
                    "codex",
                    "--dangerously-bypass-approvals-and-sandbox",
                ),
            ),
        ),
        default_provider="claude",
        directory="/home/visual/src/sase",
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(
            TmuxAgentModal(
                catalog,
                load_catalog=lambda: catalog,
                config=TmuxAgentConfig(),
                runner=_tmux_agent_runner(),
            )
        )
        await page.expect_modal("TmuxAgentModal")
        await wait_for_svg_contains(page, "tmux Agent")
        await wait_for_svg_contains(page, "not installed")
        await wait_for_svg_contains(page, "routing disabled · 42m left")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_tmux_agent_modal_120x40",
            title="ACE Launch Control — tmux Agent modal",
        )
