"""Mounted session-turn Muse parser-to-Reply-card streaming coverage."""

from __future__ import annotations

import json
from datetime import datetime
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_session_members import current_agent_session_turn_row
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


def _context_card_text(page: AcePage) -> str:
    detail = page.app.query_one("#agent-detail-panel")
    card = detail._main_deck_document.card("context")
    assert card is not None
    console = Console(file=StringIO(), record=True, width=120)
    console.print(card)
    return console.export_text()


def _build_mounted_session_agents(tmp_path: Path) -> tuple[Agent, Agent, Agent]:
    base = tmp_path / "sess"
    container_dir = base / "container"
    old_dir = base / "old"
    current_dir = base / "current"
    for directory in (container_dir, old_dir, current_dir):
        directory.mkdir(parents=True, exist_ok=True)
    (container_dir / "01_prompt.md").write_text(
        "session context stays\n", encoding="utf-8"
    )
    (old_dir / "01_prompt.md").write_text("old prompt\n", encoding="utf-8")
    (old_dir / "live_reply.md").write_text(
        "older completed turn text", encoding="utf-8"
    )
    (old_dir / "live_reply_timestamps.jsonl").write_text(
        json.dumps({"byte_offset": 0, "timestamp": "2026-10-03T12:09:00+00:00"}) + "\n",
        encoding="utf-8",
    )
    (current_dir / "01_prompt.md").write_text(
        "Wait for the gated provider reply.\n", encoding="utf-8"
    )
    (current_dir / "live_reply.md").write_text("", encoding="utf-8")
    (current_dir / "live_reply_timestamps.jsonl").write_text("", encoding="utf-8")

    container = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sess-stream",
        project_file="/tmp/sess-stream.sase",
        status="RUNNING",
        start_time=datetime(2026, 10, 3, 12, 0, 0),
        raw_suffix="20261003121000",
        agent_name="sess-stream",
        agent_session="sess-stream",
        agent_session_role="root",
        role_suffix="--root",
        llm_provider="muse",
        artifacts_dir=str(container_dir),
    )
    old = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sess-stream",
        project_file="/tmp/sess-stream.sase",
        status="DONE",
        start_time=datetime(2026, 10, 3, 11, 59, 0),
        stop_time=datetime(2026, 10, 3, 12, 0, 0),
        raw_suffix="20261003120900",
        agent_name="sess-stream",
        agent_session="sess-stream",
        agent_session_role="code",
        role_suffix="--code",
        parent_timestamp=container.raw_suffix,
        llm_provider="muse",
        artifacts_dir=str(old_dir),
    )
    current = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="sess-stream",
        project_file="/tmp/sess-stream.sase",
        status="RUNNING",
        start_time=datetime(2026, 10, 3, 12, 1, 0),
        raw_suffix="20261003121100",
        agent_name="sess-stream",
        agent_session="sess-stream",
        agent_session_role="code",
        role_suffix="--code",
        parent_timestamp=container.raw_suffix,
        workflow="run",
        appears_as_agent=True,
        llm_provider="muse",
        artifacts_dir=str(current_dir),
    )
    container.followup_agents = [old, current]
    return container, old, current


@pytest.mark.asyncio
async def test_gated_muse_stream_reaches_mounted_session_current_turn_reply(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    container, _old, current = _build_mounted_session_agents(tmp_path)
    stream_dir = Path(current.artifacts_dir or "")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(stream_dir))
    patch_startup_loaders(monkeypatch, agents=[container])

    async with AcePage(
        query='"sess-stream"',
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
        assert panel._live_reply_source is not None
        assert panel._live_reply_source.reply_identity == current.identity
        await exercise_gated_stream(
            page,
            panel,
            monkeypatch,
            tmp_path,
            stream_dir,
            expected_identity=current.identity,
            expected_dir=stream_dir,
            # Session Reply cards also render per-turn phase dividers that
            # match the timestamp-divider pattern, so exact divider counts
            # are asserted on the single-agent shapes above. Here the
            # older/newer text singleton counts prove clean concatenation.
            expected_dividers=None,
            old_text="older completed turn text",
        )
        # Older reply blocks keep their identity (two-turn roster intact)
        # while only the current turn grew, and Context is untouched.
        assert "· 2" in reply_card_text(page)
        assert "session context stays" in _context_card_text(page)

        selected = page.app._get_selected_agent()
        assert selected is not None
        turn = current_agent_session_turn_row(selected)
        assert turn is not None
        assert turn.identity == current.identity
        turn.status = "DONE"
        turn.stop_time = datetime(2026, 10, 3, 12, 2, 0)
        panel.update_display(selected)
        await wait_for_visual_idle(page)
        assert reply_card_text(page).count("A reply can stream in pieces:") == 1
        assert "the words stay together and keep growing." in reply_card_text(page)
        assert reply_card_text(page).count("older completed turn text") == 1
        assert panel._live_reply_source is None
