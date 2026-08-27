"""ACE TUI PNG snapshots for Launch Control duration modals."""

from __future__ import annotations

from collections.abc import Sequence
import subprocess

import pytest
from textual.widgets import Input, Static

from sase.ace.testing import AcePage
from sase.ace.tui.modals.models_panel_duration import (
    DurationPickerModal,
    KeepCurrentWindow,
)
import sase.ace.tui.modals.models_panel_duration as models_panel_duration
from sase.ace.tui.modals.models_panel_effort_cards import (
    DefaultEffortActionModal,
    DefaultEffortLevelModal,
)
from sase.ace.tui.modals.models_panel_runner_limit_cards import (
    RunnerLimitActionModal,
    RunnerLimitValueModal,
)
from sase.ace.tui.modals.models_panel_provider_modal import ProviderRoutingModal
from sase.ace.tui.modals.models_panel_provider_rendering import provider_duration_modal
from sase.ace.tui.modals.models_panel_provider_state import ProviderRoutingSnapshot
import sase.ace.tui.modals.models_panel_provider_modal as models_panel_provider_modal
from sase.ace.tui.modals.models_panel_time import OverrideUntilModal
import sase.ace.tui.modals.tmux_agent_modal as tmux_agent_modal
from sase.ace.tui.modals.tmux_agent_modal import TmuxAgentModal
from sase.config.tmux_agent import TmuxAgentConfig
from sase.llm_provider import TemporaryProviderDisable
from sase.tmux_agent import TmuxAgentCatalog, TmuxAgentEntry, TmuxRunner
from tests.ace.tui.visual._ace_models_panel_png_snapshot_fixtures import (
    EASTERN,
    FROZEN_NOW,
    effort_snapshot,
    provider_disable,
    provider_status,
    runner_limit_snapshot,
    time_modal_clock,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_models_panel_default_effort_action_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(
            DefaultEffortActionModal(
                effort_snapshot(), now=FROZEN_NOW, use_chezmoi=True
            )
        )
        await page.expect_modal("DefaultEffortActionModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_effort_action_120x40",
            title="ACE Launch Control — default-effort action chooser",
        )


@pytest.mark.parametrize(
    ("mode", "snapshot_name", "title"),
    [
        (
            "edit",
            "models_panel_effort_level_edit_120x40",
            "ACE Launch Control — persistent effort-level picker",
        ),
        (
            "override",
            "models_panel_effort_level_override_120x40",
            "ACE Launch Control — temporary effort-level picker",
        ),
    ],
)
async def test_models_panel_default_effort_level_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(
            DefaultEffortLevelModal(  # type: ignore[arg-type]
                mode, effort_snapshot(), now=FROZEN_NOW
            )
        )
        await page.expect_modal("DefaultEffortLevelModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


async def test_models_panel_runner_limit_action_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(
            RunnerLimitActionModal(
                runner_limit_snapshot(), now=FROZEN_NOW, use_chezmoi=True
            )
        )
        await page.expect_modal("RunnerLimitActionModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_runner_limit_action_120x40",
            title="ACE Launch Control — runner-limit action chooser",
        )


@pytest.mark.parametrize(
    ("mode", "snapshot_name", "title", "initial"),
    [
        (
            "edit",
            "models_panel_runner_limit_value_edit_120x40",
            "ACE Launch Control — persistent runner-limit editor",
            10,
        ),
        (
            "override",
            "models_panel_runner_limit_value_override_120x40",
            "ACE Launch Control — temporary runner-limit editor",
            4,
        ),
    ],
)
async def test_models_panel_runner_limit_value_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    snapshot_name: str,
    title: str,
    initial: int,
) -> None:
    patch_startup_loaders(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(
            RunnerLimitValueModal(mode, initial=initial)  # type: ignore[arg-type]
        )
        await page.expect_modal("RunnerLimitValueModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


async def test_models_panel_duration_picker_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(DurationPickerModal())
        await page.expect_modal("DurationPickerModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_duration_picker_120x40",
            title="ACE model override duration picker",
        )


async def test_models_panel_provider_duration_picker_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(provider_duration_modal("claude"))
        await page.expect_modal("DurationPickerModal")
        await wait_for_svg_contains(page, "Disable CLAUDE")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_provider_duration_picker_120x40",
            title="ACE provider-disable duration picker",
        )


async def test_models_panel_provider_duration_picker_keep_window_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(models_panel_duration, "now", lambda: FROZEN_NOW)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(
            provider_duration_modal(
                "claude",
                keep_current=KeepCurrentWindow(expires_at=FROZEN_NOW + 6_120.0),
            )
        )
        await page.expect_modal("DurationPickerModal")
        await wait_for_svg_contains(page, "Keep current window")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_provider_duration_picker_keep_window_120x40",
            title="ACE provider-disable duration picker keep-current window",
        )


async def test_models_panel_provider_routing_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(models_panel_provider_modal, "now", lambda: FROZEN_NOW)
    disable = provider_disable(
        "codex", expires_at=FROZEN_NOW + 2_520.0, source="usage_limit"
    )
    snapshot = ProviderRoutingSnapshot(
        statuses=(
            provider_status(
                "codex",
                model_count=7,
                active_disable=disable,
                affected_aliases=("medium", "xsmall"),
            ),
            provider_status("claude", model_count=11),
            provider_status("gemini", model_count=2, cli_available=False),
        ),
        provider_disables={"codex": disable},
        alias_views=(),
        provider_colors={
            "claude": "#D97757",
            "codex": "#10A37F",
            "gemini": "#87D7FF",
        },
        captured_at=FROZEN_NOW,
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(
            ProviderRoutingModal(snapshot, load_snapshot=lambda: snapshot)
        )
        await page.expect_modal("ProviderRoutingModal")
        await wait_for_svg_contains(page, "Provider Routing")
        await wait_for_svg_contains(page, "disabled · usage-limit automatic · 42m left")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_provider_routing_modal_120x40",
            title="ACE Launch Control — provider routing modal",
        )


async def test_models_panel_provider_routing_until_cleared_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(models_panel_provider_modal, "now", lambda: FROZEN_NOW)
    disable = provider_disable("codex", expires_at=None)
    snapshot = ProviderRoutingSnapshot(
        statuses=(
            provider_status(
                "codex",
                model_count=7,
                active_disable=disable,
                affected_aliases=("medium", "xsmall", "legacy_blog"),
            ),
            provider_status("claude", model_count=11),
        ),
        provider_disables={"codex": disable},
        alias_views=(),
        provider_colors={"claude": "#D97757", "codex": "#10A37F"},
        captured_at=FROZEN_NOW,
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(
            ProviderRoutingModal(snapshot, load_snapshot=lambda: snapshot)
        )
        await page.expect_modal("ProviderRoutingModal")
        await wait_for_svg_contains(page, "disabled · manual · until cleared")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_provider_routing_until_cleared_120x40",
            title="ACE Launch Control — provider routing until cleared",
        )


async def test_models_panel_provider_routing_modal_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(models_panel_provider_modal, "now", lambda: FROZEN_NOW)
    disable = provider_disable("codex", expires_at=FROZEN_NOW + 2_520.0)
    snapshot = ProviderRoutingSnapshot(
        statuses=(
            provider_status(
                "codex",
                model_count=7,
                active_disable=disable,
                affected_aliases=("medium", "xsmall"),
            ),
            provider_status("claude", model_count=11),
            provider_status("gemini", model_count=2, cli_available=False),
            provider_status("opencode", model_count=3),
        ),
        provider_disables={"codex": disable},
        alias_views=(),
        provider_colors={
            "claude": "#D97757",
            "codex": "#10A37F",
            "gemini": "#87D7FF",
            "opencode": "#B48EAD",
        },
        captured_at=FROZEN_NOW,
    )

    async with AcePage(query='"visual"', patches=patches(), size=(70, 32)) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(
            ProviderRoutingModal(snapshot, load_snapshot=lambda: snapshot)
        )
        await page.expect_modal("ProviderRoutingModal")
        await wait_for_svg_contains(page, "Provider Routing")
        await wait_for_svg_contains(page, "disabled · manual · 42m left")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "models_panel_provider_routing_modal_narrow_70x32",
            title="ACE Launch Control — narrow provider routing modal",
        )


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


@pytest.mark.parametrize(
    ("value", "snapshot_name", "title"),
    [
        ("", "models_panel_until_neutral_120x40", "ACE override until (neutral)"),
        ("5pm", "models_panel_until_valid_120x40", "ACE override until (valid)"),
        (
            "today 1pm",
            "models_panel_until_error_120x40",
            "ACE override until (error)",
        ),
    ],
)
async def test_models_panel_override_until_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    value: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        modal = OverrideUntilModal(timezone=EASTERN, clock=time_modal_clock)
        page.app.push_screen(modal)
        await page.expect_modal("OverrideUntilModal")
        await wait_for_svg_contains(page, "Override Until")
        field = modal.query_one("#override-until-input", Input)
        if value:
            field.value = value
        expected_class = {
            "": "until-neutral",
            "5pm": "until-valid",
            "today 1pm": "until-error",
        }[value]
        preview = modal.query_one("#override-until-preview", Static)
        await wait_for_state(
            page,
            lambda: (
                field.has_focus
                and field.value == value
                and preview.has_class(expected_class)
            ),
            description=f"override-until {expected_class} preview",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)
