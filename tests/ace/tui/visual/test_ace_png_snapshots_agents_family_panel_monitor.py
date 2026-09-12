"""ACE PNG snapshots for family panel monitor shell metadata and conversation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from rich.text import Text

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_family_members import concrete_family_shell_rows
from sase.ace.tui.widgets import AgentList
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.monitor.models import MONITOR_FOLLOWUP_DEGRADED_OUTCOME
from sase.monitor.presentation import HOST_COMPLETED_OUTCOME
from sase.monitor_state import monitor_state_bucket
from tests.ace.tui.visual._ace_agents_png_snapshot_family_panel_fixtures import (
    _family_agents,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
    pin_agents_visual_now,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _monitor_state_agent(
    tmp_path: Path,
    slug: str,
    *,
    monitor_state: str,
    status: str,
    exit_code: int | None = None,
    output: str = "monitor output is still pending\n",
    followup_outcome: str | None = None,
    followup_error: str | None = None,
    followup_degraded_reason: str | None = None,
    host_completion_status: str | None = None,
    host_completion_message: str | None = None,
    diagnostic_manifest_ref: str | None = None,
    retained_log_ref: str | None = None,
    result_ref: str | None = None,
    checkpoint_ref: str | None = None,
    budget_decision_path: str | None = None,
) -> Agent:
    artifacts_dir = tmp_path / f"monitor-{slug}"
    artifacts_dir.mkdir()
    (artifacts_dir / "live_reply.md").write_text(output, encoding="utf-8")
    started = datetime(2026, 9, 12, 12, 0, 0)
    terminal = monitor_state != "running"
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=f"visual-monitor-{slug}",
        project_file="/workspace/sase/visual_project.sase",
        status=status,
        status_bucket=monitor_state_bucket(monitor_state),
        start_time=started,
        run_start_time=started,
        stop_time=started if terminal else None,
        raw_suffix=f"20260912120000-{slug}",
        artifacts_dir=str(artifacts_dir),
        agent_name=f"visual-monitor-{slug}--mon",
        agent_family=f"visual-monitor-{slug}",
        agent_family_role="monitor",
        role_suffix="--mon",
        monitor_id=f"mon-{slug}-abcdef",
        monitor_state=monitor_state,
        monitor_label=f"monitor {slug}",
        monitor_start_status="TESTING",
        monitor_stop_status="TESTED",
        monitor_command="just check-full --include monitor-state-contract",
        monitor_cwd="/workspace/sase",
        monitor_reason=f"Visual contract for {slug} monitor recovery state",
        monitor_next_action="Inspect the frozen monitor result and finish the work.",
        monitor_next_model="codex/gpt-5",
        monitor_next_output="auto",
        monitor_profile="verify",
        monitor_exit_code=exit_code,
        monitor_timeout_seconds=2700.0,
        monitor_idle_timeout_seconds=600.0,
        monitor_completion_ref="host-completion:visual"
        if host_completion_status
        else None,
        monitor_followup_outcome=followup_outcome,
        monitor_followup_error=followup_error,
        monitor_followup_degraded_reason=followup_degraded_reason,
        monitor_host_completion_status=host_completion_status,
        monitor_host_completion_message=host_completion_message,
        monitor_diagnostic_manifest_ref=diagnostic_manifest_ref,
        monitor_retained_log_ref=retained_log_ref,
        continuation_monitor_result_ref=result_ref,
        continuation_checkpoint_ref=checkpoint_ref,
        continuation_node_ref="artifact:visual-node" if result_ref else None,
        continuation_manifest_ref="artifact:visual-manifest" if result_ref else None,
        monitor_budget_decision_path=budget_decision_path,
        llm_provider="codex",
        model="gpt-5",
    )


_MONITOR_STATE_CASES = (
    (
        "running",
        {
            "monitor_state": "running",
            "status": "TESTING",
            "output": "collecting diagnostics...\n",
        },
    ),
    (
        "host_completed",
        {
            "monitor_state": "completed",
            "status": "TESTED",
            "exit_code": 0,
            "output": "all checks passed\n",
            "followup_outcome": HOST_COMPLETED_OUTCOME,
            "host_completion_status": "completed_by_host",
            "host_completion_message": "Required checks passed in 4m12s.",
            "result_ref": "artifact:host-result",
        },
    ),
    (
        "failed_diagnostics",
        {
            "monitor_state": "failed",
            "status": "TESTED",
            "exit_code": 1,
            "output": "FAILED tests/monitor/test_delivery.py::test_case\n",
            "diagnostic_manifest_ref": "artifact:diagnostics-failed",
            "retained_log_ref": "artifact:retained-log",
            "result_ref": "artifact:failed-result",
            "checkpoint_ref": "local:continuation/checkpoints/failed.yml",
        },
    ),
    (
        "timeout",
        {
            "monitor_state": "timeout",
            "status": "TESTED",
            "exit_code": 124,
            "output": "timed out waiting for quiet shard\n",
            "result_ref": "artifact:timeout-result",
            "checkpoint_ref": "local:continuation/checkpoints/timeout.yml",
        },
    ),
    (
        "lost",
        {
            "monitor_state": "lost",
            "status": "TESTED",
            "output": "last retained line before reboot\n",
            "result_ref": "artifact:lost-result",
        },
    ),
    (
        "degraded",
        {
            "monitor_state": "completed",
            "status": "TESTED",
            "exit_code": 0,
            "output": "checks passed, workspace fallback used\n",
            "followup_outcome": MONITOR_FOLLOWUP_DEGRADED_OUTCOME,
            "followup_degraded_reason": "original workspace claim unavailable",
            "result_ref": "artifact:degraded-result",
        },
    ),
    (
        "needs_attention",
        {
            "monitor_state": "completed",
            "status": "TESTED",
            "exit_code": 0,
            "output": "checks passed, continuation could not launch\n",
            "followup_outcome": "not-launchable",
            "followup_error": "context_budget_exceeded; run monitor resume with checkpoint",
            "result_ref": "artifact:attention-result",
            "checkpoint_ref": "local:continuation/checkpoints/attention.yml",
            "budget_decision_path": "/workspace/sase/.sase/monitor-budget.json",
        },
    ),
)


@pytest.mark.parametrize(("width", "height"), [(90, 40), (120, 40)])
@pytest.mark.parametrize(("slug", "overrides"), _MONITOR_STATE_CASES)
async def test_monitor_state_detail_png_snapshots(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    slug: str,
    overrides: dict[str, object],
    width: int,
    height: int,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 9, 12, 12, 6, 0))
    agent = _monitor_state_agent(tmp_path, slug, **overrides)  # type: ignore[arg-type]
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(
        query=f'"visual-monitor-{slug}"',
        size=(width, height),
        patches=patches(),
    ) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        assert page.app._agents[page.app.current_idx].is_monitor
        panel = page.query_one_widget("#agent-prompt-panel", AgentPromptPanel)
        for _ in range(20):
            if panel.active_section_identity == "monitor":
                break
            await page.press("ctrl+j")
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, f"visual-monitor-{slug}")
        if width >= 120:
            assert panel.active_section_identity == "monitor"
            assert_page_svg_contains(page, "MONITOR")
            assert_page_svg_contains(page, "Result:")
            assert_page_svg_contains(page, "Next:")
            assert_page_svg_contains(page, "Evidence:")
        ace_png_visual.assert_page_png(
            page,
            f"agents_monitor_state_{slug}_{width}x{height}",
            title=f"ACE monitor detail {slug} {width}x{height}",
        )


async def test_family_panel_shells_monitor_metadata_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 18, 13, 8, 0))
    patch_startup_loaders(
        monkeypatch,
        agents=_family_agents(
            tmp_path,
            member_count=2,
            with_content=False,
            with_monitor=True,
            monitor_command=(
                "just check-full --include visual --include slow "
                "--include every-family-shell-metadata-case"
            ),
            monitor_reason=(
                "Full-suite verification before landing the family shell "
                "metadata renderer"
            ),
        ),
    )

    async with AcePage(
        query='"visual-family-root"',
        size=(120, 40),
        patches=patches(),
    ) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        container = page.app._agents[page.app.current_idx]
        assert container.is_family_container_row is True
        shells = concrete_family_shell_rows(container)
        assert [shell.is_monitor for shell in shells] == [False, False, True]
        monitor = shells[2]
        assert monitor.parent_timestamp != container.raw_suffix
        jump_map = page.app._member_jump_maps[container.identity]
        assert [target.number for target in jump_map.targets] == ["0", "1", "2"]
        assert jump_map.targets[2].member_identity == monitor.identity
        assert_page_svg_contains(page, "Shells:")
        assert_page_svg_contains(page, "⚙")
        assert_page_svg_contains(page, "why")
        assert_page_svg_contains(page, "Full-suite")
        assert_page_svg_contains(page, "verification")
        assert_page_svg_contains(page, "FAMILY SHELLS")
        ace_png_visual.assert_page_png(
            page,
            "agents_family_panel_shells_monitor_120x40",
            title="ACE family panel shell metadata with monitor",
        )

        panel = page.query_one_widget("#agent-prompt-panel", AgentPromptPanel)
        for _ in range(20):
            if panel.active_section_identity == "members":
                break
            await page.press("ctrl+j")
        assert panel.active_section_identity == "members"
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "FAMILY SHELLS")
        assert_page_svg_contains(page, "--plan")
        assert_page_svg_contains(page, "--mon")
        assert_page_svg_contains(page, "⚙ MONITOR")
        assert_page_svg_contains(page, "just check")
        ace_png_visual.assert_page_png(
            page,
            "agents_family_panel_shells_monitor_roster_120x40",
            title="ACE family panel FAMILY SHELLS roster with monitor",
        )

        await page.press("2")
        await page.wait_for(
            lambda _state: page.app._agents[page.app.current_idx].is_monitor
        )
        assert page.app._agents[page.app.current_idx].identity == monitor.identity


async def test_family_conversation_monitor_phase_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 18, 13, 8, 0))
    patch_startup_loaders(
        monkeypatch,
        agents=_family_agents(
            tmp_path,
            member_count=2,
            with_content=False,
            with_monitor=True,
        ),
    )

    async with AcePage(query='"visual-family"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        container = page.app._agents[page.app.current_idx]
        assert container.is_family_container_row is True
        panel = page.query_one_widget("#agent-prompt-panel", AgentPromptPanel)
        for _ in range(20):
            await page.press("ctrl+j")
            if panel.active_section_identity == "agent-reply":
                break
        assert panel.active_section_identity == "agent-reply"
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "MONITOR")
        assert_page_svg_contains(page, "just check-full")
        panel = page.app.query_one("#agent-list-panel", AgentList)
        assert "⚙1" in Text.from_markup(panel.border_title).plain
        ace_png_visual.assert_page_png(
            page,
            "agents_family_conversation_monitor_120x40",
            title="ACE family conversation with monitor phase",
        )
