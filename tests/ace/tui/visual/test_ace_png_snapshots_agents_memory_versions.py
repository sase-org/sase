"""PNG goldens for the Agents-tab MEMORY lane version chips (phase `agents-bridge`).

The Agents context card with chips and the launch row in dark and light
themes at 120x40. History data is injected deterministically (no
git/file I/O): ``AceMemoryHistory`` and the launch evidence read are
faked, so the chips and the ``AGENTS.md as launched`` row render from
canned version results.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets import AgentDetail
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from sase.ace.tui.widgets.prompt_panel._agent_display_header_summary import (
    DetailHeaderSummary,
)
from sase.ace.tui.widgets.renderable_text import renderable_to_text
from sase.memory.read_log import READ_LOG_SCHEMA_VERSION, MemoryReadEvent
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    choose_agent_metadata_view,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patch_startup_loaders,
    patches,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_BLOB_NOW = "b" * 40
_BLOB_PAST = "a" * 40
_BLOB_LAUNCH = "c" * 40


def _reads() -> list[MemoryReadEvent]:
    return [
        MemoryReadEvent(
            schema_version=READ_LOG_SCHEMA_VERSION,
            id="visual-read-gotchas",
            timestamp="2026-09-28T10:02:11+00:00",
            project="",
            cwd="/tmp/visual-bridge",
            canonical_path="gotchas.md",
            resolved_path="/tmp/visual-bridge/sase/memory/gotchas.md",
            agent_name="visual.bridge.agent",
            agent_source="SASE_AGENT_NAME",
            artifacts_dir="/tmp/visual-bridge/artifacts",
            reason="need keymap conventions",
            byte_count=64,
            frontmatter_stripped=False,
            selectors=("gotchas.md",),
            blob_oid=_BLOB_NOW,
        ),
        MemoryReadEvent(
            schema_version=READ_LOG_SCHEMA_VERSION,
            id="visual-read-dispatch",
            timestamp="2026-09-28T10:04:40+00:00",
            project="",
            cwd="/tmp/visual-bridge",
            canonical_path="dispatch.md",
            resolved_path="/tmp/visual-bridge/sase/memory/dispatch.md",
            agent_name="visual.bridge.agent",
            agent_source="SASE_AGENT_NAME",
            artifacts_dir="/tmp/visual-bridge/artifacts",
            reason="remote dispatch rules",
            byte_count=64,
            frontmatter_stripped=False,
            selectors=("dispatch.md",),
            blob_oid=_BLOB_PAST,
        ),
    ]


class _FakeHistoryService:
    def project_scope(self, root: Any) -> SimpleNamespace:
        return SimpleNamespace(scope_key="project:visual", repo_root=str(root))

    def home_scope(self) -> None:
        return None


class _FakeVersionHistory:
    """Canned ``AceMemoryHistory`` standing in for git-backed resolution."""

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.service = _FakeHistoryService()

    def version_for_blob(self, scope: Any, selector: str, oid: str) -> dict[str, Any]:
        if oid == _BLOB_NOW:
            return {
                "ordinal": 25,
                "version": {"ordinal": 25},
                "newest": 25,
                "newest_version": {"ordinal": 25},
                "newer_count": 0,
                "now_matches": True,
            }
        if oid == _BLOB_PAST:
            return {
                "ordinal": 12,
                "version": {"ordinal": 12},
                "newest": 14,
                "newest_version": {"ordinal": 14},
                "newer_count": 2,
                "now_matches": False,
            }
        if oid == _BLOB_LAUNCH:
            return {
                "ordinal": 258,
                "version": {"ordinal": 258},
                "newest": 260,
                "newest_version": {"ordinal": 260},
                "newer_count": 2,
                "now_matches": False,
            }
        raise LookupError(f"no version blob:{oid}")


def _install_fakes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.memory_history.AceMemoryHistory",
        _FakeVersionHistory,
    )
    evidence = {
        "workspace_head": "f" * 40,
        "instruction_snapshot": [
            {
                "path": str(tmp_path / "AGENTS.md"),
                "repo": "project",
                "blob_oid": _BLOB_LAUNCH,
                "tracked": True,
            }
        ],
    }
    monkeypatch.setattr(
        "sase.ace.tui.widgets.prompt_panel._agent_memory_versions._read_launch_evidence",
        lambda _agent: dict(evidence),
    )


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "agents_memory_version_chips_dark_120x40",
            "ACE agents MEMORY lane version chips dark theme",
        ),
        (
            "textual-light",
            "agents_memory_version_chips_light_120x40",
            "ACE agents MEMORY lane version chips light theme",
        ),
    ],
)
async def test_agents_memory_version_chips_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="visual-bridge",
        project_file="/workspace/sase/visual_project.sase",
        status="RUNNING",
        start_time=datetime(2026, 9, 28, 10, 0, 0),
        raw_suffix="20260928100000",
        agent_name="visual.bridge.agent",
        step_type="bash",
        workspace_dir=str(tmp_path),
        llm_provider="codex",
        model="gpt-5",
    )
    _install_fakes(monkeypatch, tmp_path)
    patch_startup_loaders(monkeypatch, agents=[agent], memory_reads=_reads())

    async with AcePage(query='"visual-bridge"', patches=patches()) as page:
        await wait_for_startup(page)
        page.app.theme = theme
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await choose_agent_metadata_view(page)
        panel = page.app.query_one("#agent-prompt-panel", AgentPromptPanel)
        await page.wait_for(
            lambda _state: (
                "AGENTS.md as launched" in (renderable_to_text(panel.content) or "")
            )
        )
        await page.press("Z")
        await page.expect_no_modal()
        detail = page.app.query_one("#agent-detail-panel", AgentDetail)
        assert detail.is_deck_zoomed is True
        await page.wait_for(
            lambda _state: (
                "newer since launch" in (renderable_to_text(panel.content) or "")
            )
        )
        metadata = renderable_to_text(panel.content) or ""
        assert "SASE CONTEXT" in metadata
        assert "AGENTS.md as launched" in metadata
        assert "newer since launch" in metadata
        summary = _latest_memory_summary(panel, agent)
        assert summary is not None
        assert summary.memory_launch_row is not None
        assert summary.memory_version_chips, "chips resolve in the visual app"
        await wait_for_svg_contains(page, "as launched")
        await wait_for_svg_contains(page, "since launch")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


def _latest_memory_summary(
    panel: AgentPromptPanel, agent: Agent
) -> DetailHeaderSummary | None:
    """Return the cached header summary for *agent*, if any."""
    cache = getattr(panel, "_agent_detail_header_summary_cache", None)
    if not cache:
        return None
    entry = cache.get(agent.identity)
    if entry is not None:
        return entry.summary
    return None
