"""ACE TUI PNG visual coverage for Agents-tab artifact type icons."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from sase.core.artifact_file_facade import store_default_artifact_file
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _artifact_icon_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Agent:
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    artifacts_dir = (
        sase_home / "projects" / "visual" / "artifacts" / "ace-run" / "20260711120000"
    )
    artifacts_dir.mkdir(parents=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    for filename, kind in (
        ("diagram.png", None),
        ("walkthrough.mp4", "file"),
        ("notes.md", "plan"),
        ("report.pdf", "file"),
        ("results.csv", "file"),
    ):
        source = workspace / filename
        source.write_bytes(b"visual artifact")
        assert (
            store_default_artifact_file(
                source,
                artifacts_dir,
                kind=kind,
                workspace_dir=str(workspace),
            )
            is not None
        )

    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-artifact-icons",
        project_file="/workspace/sase/visual_project.sase",
        status="DONE",
        start_time=datetime(2026, 7, 11, 12, 0, 0),
        stop_time=datetime(2026, 7, 11, 12, 5, 0),
        raw_suffix="20260711120000",
        agent_name="artifact.icon.gallery",
        workspace_dir=str(workspace),
        artifacts_dir=str(artifacts_dir),
    )


async def test_agents_artifact_file_type_icons_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    agent = _artifact_icon_agent(tmp_path, monkeypatch)
    patch_startup_loaders(monkeypatch, agents=[agent])

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Files:")
        for icon in ("▨", "▶", "▤", "•"):
            assert_page_svg_contains(page, icon)

        ace_png_visual.assert_page_png(
            page,
            "agents_artifact_type_icons_120x40",
            title="ACE agents artifact-file type icons",
        )
