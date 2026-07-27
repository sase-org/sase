"""Tests for the panel-local annotated hint document cache."""

from __future__ import annotations

from pathlib import Path

from sase.ace.tui.util.lazy_syntax import CachedRenderable
from sase.ace.tui.widgets.prompt_panel._agent_display_header_summary import (
    cache_detail_header_summary,
)
from sase.ace.tui.widgets.prompt_panel._agent_display_state import (
    DetailHeaderSummary,
)

from ._agent_display_helpers import (
    FakePromptPanel,
    make_artifact_agent,
    plain_of,
)


def test_repeat_hint_render_reuses_result_and_renderable(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    agent = make_artifact_agent(
        tmp_path,
        status="DONE",
        workspace_dir=str(workspace),
    )
    Path(agent.response_path or "").write_text(
        "Open src/reused.py\n",
        encoding="utf-8",
    )
    panel = FakePromptPanel()
    cache_detail_header_summary(panel, agent, DetailHeaderSummary())

    first = panel.update_display_with_hints(agent)
    first_renderable = panel.captured[-1]
    second = panel.update_display_with_hints(agent)

    assert first is second
    assert panel.captured[-1] is first_renderable
    assert isinstance(first_renderable, CachedRenderable)
    assert first.file_hints == {
        1: str(workspace / "src/raw.py"),
        2: str(workspace / "src/reused.py"),
    }


def test_changed_reply_invalidates_hint_document_and_mappings(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    agent = make_artifact_agent(
        tmp_path,
        status="DONE",
        workspace_dir=str(workspace),
    )
    response_path = Path(agent.response_path or "")
    response_path.write_text("Open src/first.py\n", encoding="utf-8")
    panel = FakePromptPanel()
    cache_detail_header_summary(panel, agent, DetailHeaderSummary())

    first = panel.update_display_with_hints(agent)
    first_renderable = panel.captured[-1]
    response_path.write_text(
        "Open src/second-and-longer.py\n",
        encoding="utf-8",
    )
    second = panel.update_display_with_hints(agent)

    assert second is not first
    assert panel.captured[-1] is not first_renderable
    assert str(workspace / "src/first.py") not in second.file_hints.values()
    assert str(workspace / "src/second-and-longer.py") in second.file_hints.values()
    assert "[2] src/second-and-longer.py" in plain_of(panel.captured[-1])


def test_attempt_pinned_number_isolated_in_hint_cache(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    agent = make_artifact_agent(
        tmp_path,
        status="DONE",
        workspace_dir=str(workspace),
    )
    panel = FakePromptPanel()
    cache_detail_header_summary(panel, agent, DetailHeaderSummary())

    panel.attempt_pinned_number = None
    unpinned = panel.update_display_with_hints(agent)
    unpinned_renderable = panel.captured[-1]
    panel.attempt_pinned_number = 1
    pinned = panel.update_display_with_hints(agent)

    assert pinned is not unpinned
    assert panel.captured[-1] is not unpinned_renderable
