"""Mounted workflow Muse parser-to-Reply-card streaming coverage."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models._loaders._workflow_loaders import load_workflow_agents
from sase.ace.tui.models._loaders._workflow_step_loaders import (
    load_workflow_agent_steps,
)
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from tests.ace.tui._live_reply_follow_mounted_helpers import (
    exercise_gated_stream,
    reply_card_text,
    wait_for_page,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patch_startup_loaders,
    patches,
    wait_for_startup,
    wait_for_visual_idle,
)


def _write_mounted_prompt_set(
    artifacts_dir: Path, *, step_name: str | None = None
) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "raw_prompt.md").write_text(
        "Run the mounted Muse stream fixture.\n", encoding="utf-8"
    )
    if step_name is None:
        (artifacts_dir / "01_prompt.md").write_text(
            "Wait for the gated provider reply.\n", encoding="utf-8"
        )
    else:
        (artifacts_dir / f"01-{step_name}_prompt.md").write_text(
            "Wait for the gated provider step reply.\n", encoding="utf-8"
        )
    (artifacts_dir / "live_reply.md").write_text("", encoding="utf-8")
    (artifacts_dir / "live_reply_timestamps.jsonl").write_text("", encoding="utf-8")


def _build_mounted_workflow_fixture(
    tmp_path: Path, *, cl_name: str, workflow_name: str = "run"
) -> tuple[Path, Path]:
    project_dir = tmp_path / "demo"
    timestamp_dir = project_dir / "artifacts" / "ace-run" / "20261003120000"
    timestamp_dir.mkdir(parents=True)
    (timestamp_dir / "workflow_state.json").write_text(
        json.dumps(
            {
                "workflow_name": workflow_name,
                "context": {"cl_name": cl_name},
                "status": "running",
                "appears_as_agent": True,
                "start_time": "2026-10-03T12:00:00",
                "steps": [],
            }
        ),
        encoding="utf-8",
    )
    (timestamp_dir / "prompt_step_main.json").write_text(
        json.dumps(
            {
                "workflow_name": workflow_name,
                "step_name": "main",
                "step_type": "agent",
                "status": "in_progress",
                "artifacts_dir": str(timestamp_dir),
                "llm_provider": "muse",
                "model": "muse-spark",
            }
        ),
        encoding="utf-8",
    )
    (timestamp_dir / "agent_meta.json").write_text(
        json.dumps({"name": cl_name, "llm_provider": "muse", "model": "muse-spark"}),
        encoding="utf-8",
    )
    _write_mounted_prompt_set(timestamp_dir, step_name="main")
    # Keep the root prompt newest so the shared directory still resolves the
    # root view to its own prompt file while the step uses its step file.
    step_prompt = timestamp_dir / "01-main_prompt.md"
    root_prompt = timestamp_dir / "01_prompt.md"
    (timestamp_dir / "raw_prompt.md").write_text(
        "Run the mounted Muse stream fixture.\n", encoding="utf-8"
    )
    root_prompt.write_text("Wait for the gated provider reply.\n", encoding="utf-8")
    step_stat = step_prompt.stat()
    os_utime_ns = step_stat.st_mtime_ns + 2_000_000_000
    os.utime(root_prompt, ns=(step_stat.st_atime_ns, os_utime_ns))
    return project_dir, timestamp_dir


@pytest.mark.asyncio
async def test_gated_muse_stream_reaches_mounted_workflow_root_reply(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_dir, timestamp_dir = _build_mounted_workflow_fixture(
        tmp_path, cl_name="muse-stream-workflow-root"
    )
    roots = load_workflow_agents(timestamp_dirs=[(project_dir, timestamp_dir)])
    assert len(roots) == 1
    agent = roots[0]
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(timestamp_dir))
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(
        query='"muse-stream-workflow-root"',
        patches=patches(),
    ) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)
        await page.press("j")
        await wait_for_visual_idle(page)
        panel = page.query_one_widget("#agent-prompt-panel", AgentPromptPanel)
        await wait_for_page(
            page,
            lambda: panel._live_reply_source is not None,
            "selected live reply source setup",
        )
        await exercise_gated_stream(
            page,
            panel,
            monkeypatch,
            tmp_path,
            timestamp_dir,
            expected_identity=agent.identity,
            expected_dir=timestamp_dir,
        )

        selected = page.app._get_selected_agent()
        assert selected is not None
        selected.status = "DONE"
        selected.stop_time = datetime(2026, 10, 3, 12, 1, 0)
        panel.update_display(selected)
        await wait_for_visual_idle(page)
        assert reply_card_text(page).count("A reply can stream in pieces:") == 1
        assert "the words stay together and keep growing." in reply_card_text(page)
        assert panel._live_reply_source is None


@pytest.mark.asyncio
async def test_gated_muse_stream_reaches_mounted_workflow_step_reply(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from sase.ace.tui.actions.navigation._agent_reveal import (
        prepare_agent_navigation_target,
        reveal_agent_navigation_target,
    )

    project_dir, timestamp_dir = _build_mounted_workflow_fixture(
        tmp_path, cl_name="muse-stream-workflow-step"
    )
    roots = load_workflow_agents(timestamp_dirs=[(project_dir, timestamp_dir)])
    steps, _meta = load_workflow_agent_steps(
        timestamp_dirs=[(project_dir, timestamp_dir)]
    )
    assert len(roots) == 1
    assert len(steps) == 1
    agent = steps[0]
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(timestamp_dir))
    patch_startup_loaders(monkeypatch, agents=[*roots, *steps])

    async with AcePage(
        query="",
        patches=patches(),
    ) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)
        await page.press("j")
        await wait_for_visual_idle(page)
        # Workflow agent steps nest under their parent workflow row. Reveal
        # the loader-created step through the production jump-to-agent path,
        # then move the highlight with real keys like a user would.
        plan, failure = prepare_agent_navigation_target(
            page.app, agent.identity, require_current=False
        )
        assert failure is None, failure
        assert plan is not None
        outcome = reveal_agent_navigation_target(page.app, plan)
        assert outcome.succeeded, outcome.failure
        await wait_for_visual_idle(page)
        for _ in range(10):
            selected = page.app._get_selected_agent()
            if selected is not None and selected.identity == agent.identity:
                break
            await page.press("j")
            await wait_for_visual_idle(page)
        selected = page.app._get_selected_agent()
        assert selected is not None
        assert selected.identity == agent.identity
        panel = page.query_one_widget("#agent-prompt-panel", AgentPromptPanel)
        await wait_for_page(
            page,
            lambda: panel._live_reply_source is not None,
            "selected live reply source setup",
        )
        await exercise_gated_stream(
            page,
            panel,
            monkeypatch,
            tmp_path,
            timestamp_dir,
            expected_identity=agent.identity,
            expected_dir=timestamp_dir,
        )

        selected = page.app._get_selected_agent()
        assert selected is not None
        selected.status = "DONE"
        selected.stop_time = datetime(2026, 10, 3, 12, 1, 0)
        panel.update_display(selected)
        await wait_for_visual_idle(page)
        assert reply_card_text(page).count("A reply can stream in pieces:") == 1
        assert "the words stay together and keep growing." in reply_card_text(page)
        assert panel._live_reply_source is None
