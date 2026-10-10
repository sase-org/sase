"""sase's TUI PNG visual snapshots for auto-restart UX (phase sase-1j6.8).

Covers the amber ``↻ RESTARTING`` row (pending and deferred), the declined
``FAILED`` row with its dim reason, and the replacement's provenance block.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
    pin_agents_visual_now,
    prompt_header_and_body_text,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_EVIDENCE_DIR = "/home/visual/.sase/restarts/20261009-visual"

_PROVENANCE: dict[str, object] = {
    "of_artifacts_dir": "/artifacts/ace-run/20261009120000",
    "of_timestamp": "20261009120000",
    "lineage_root": "20261009120000",
    "episode_id": "sase@9fd8a08",
    "ledger_key": "sase__20261009120000",
    "evidence_dir": _EVIDENCE_DIR,
    "signature": "ImportError cannot import name auto_launch_prefix",
    "from_rev": "9c5000f",
    "to_rev": "9fd8a08",
    "culprit_commit": "9fd8a081f4",
    "culprit_subject": "feat(autonomy): structural inheritance",
    "restarted_at": "2026-10-09T12:05:00+00:00",
}


def auto_restart_row_agents() -> list[Agent]:
    started = datetime(2026, 10, 9, 12, 0, 0)
    project_file = "/workspace/sase/visual_project.sase"
    pending = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-restart-pending",
        project_file=project_file,
        status="RESTARTING",
        start_time=started,
        stop_time=datetime(2026, 10, 9, 12, 4, 0),
        raw_suffix="20261009120000-pending",
        agent_name="visual.pending",
        recovery_state="pending",
        recovery_episode_id="sase@9fd8a08",
        error_message="ImportError: cannot import name 'auto_launch_prefix'",
    )
    deferred = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-restart-deferred",
        project_file=project_file,
        status="RESTARTING",
        start_time=started,
        stop_time=datetime(2026, 10, 9, 12, 4, 30),
        raw_suffix="20261009120100-deferred",
        agent_name="visual.deferred",
        recovery_state="deferred",
        error_message="ImportError: cannot import name 'auto_launch_prefix'",
    )
    declined = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-restart-declined",
        project_file=project_file,
        status="FAILED",
        start_time=started,
        stop_time=datetime(2026, 10, 9, 12, 5, 0),
        raw_suffix="20261009120200-declined",
        agent_name="visual.declined",
        recovery_state="declined",
        recovery_reason_text="auto-restart skipped — already restarted once",
        error_message="ImportError: cannot import name 'auto_launch_prefix'",
    )
    return [pending, deferred, declined]


def auto_restart_replacement_agents() -> list[Agent]:
    started = datetime(2026, 10, 9, 12, 0, 0)
    project_file = "/workspace/sase/visual_project.sase"
    return [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name="visual-restart-replacement",
            project_file=project_file,
            status="DONE",
            start_time=started,
            stop_time=datetime(2026, 10, 9, 12, 9, 0),
            raw_suffix="20261009120500-replacement",
            agent_name="visual.pending",
            llm_provider="codex",
            model="gpt-5",
            auto_restart_provenance=dict(_PROVENANCE),
            extra_files=[f"{_EVIDENCE_DIR}/error_report.md"],
        ),
    ]


async def test_agents_auto_restart_rows_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 10, 9, 12, 10, 0))
    patch_startup_loaders(monkeypatch, agents=auto_restart_row_agents())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 3)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "↻ RESTARTING")
        assert_page_svg_contains(page, "waiting for the sase update")
        assert_page_svg_contains(page, "already restarted once")
        ace_png_visual.assert_page_png(
            page,
            "agents_auto_restart_rows_120x40",
            title="ACE agents auto-restart rows",
        )


async def test_agents_auto_restart_provenance_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pin_agents_visual_now(monkeypatch, datetime(2026, 10, 9, 12, 10, 0))
    patch_startup_loaders(monkeypatch, agents=auto_restart_replacement_agents())

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "auto-restarted")
        assert_page_svg_contains(page, "visual.pending")
        prompt = page.app.query_one("#agent-prompt-panel", AgentPromptPanel)
        prompt_text = prompt_header_and_body_text(prompt) or ""
        assert "Auto-restarted after sase update 9c5000f → 9fd8a08" in prompt_text
        assert "auto_launch_prefix" in prompt_text
        assert "error_report.md" in prompt_text
        ace_png_visual.assert_page_png(
            page,
            "agents_auto_restart_provenance_120x40",
            title="ACE agents auto-restart provenance",
        )
