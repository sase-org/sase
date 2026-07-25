"""PNG snapshot coverage for question notification summaries."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.ace.tui.models.agent import Agent, AgentType
from sase.notifications import Notification
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


async def test_notification_question_summary_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    response_dir = tmp_path / "question"
    response_dir.mkdir()
    (response_dir / "question_request.json").write_text(
        json.dumps(
            {
                "questions": [
                    {
                        "header": "Protected memory regenerated",
                        "question": (
                            "The commit hook regenerated protected memory files. "
                            "How should I proceed with the pending commit?"
                        ),
                        "options": [
                            {
                                "label": "Amend and keep",
                                "description": "Fold the regenerated files into this commit",
                            },
                            {
                                "label": "Revert regeneration",
                                "description": "Restore the protected versions",
                            },
                            {
                                "label": "Abort",
                                "description": "Let me inspect manually",
                            },
                        ],
                    },
                    {
                        "header": "Verification",
                        "question": "Which checks should run before I continue?",
                        "options": [
                            {"label": "Unit tests"},
                            {"label": "Visual snapshots"},
                        ],
                        "multiSelect": True,
                    },
                ],
                "session_id": "3f2a1234567890",
            }
        ),
        encoding="utf-8",
    )
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="memory-protection",
        project_file="/workspace/sase/visual_project.sase",
        status="QUESTION",
        start_time=datetime(2026, 7, 14, 8, 0, 0),
        raw_suffix="20260714080000",
        agent_name="codex--fix-hook",
        llm_provider="codex",
        model="gpt-5.6-sol",
    )
    notification = Notification(
        id="visual-question",
        timestamp="2026-07-14T08:00:00-04:00",
        sender="question",
        notes=["How should I proceed with the regenerated protected files?"],
        action="UserQuestion",
        action_data={
            "response_dir": str(response_dir),
            "session_id": "3f2a1234567890",
            "agent_cl_name": "memory-protection",
            "agent_timestamp": "20260714080000",
        },
    )
    patch_startup_loaders(monkeypatch, agents=[agent])
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_question.format_relative_time",
        lambda _timestamp: "4m ago",
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_options.format_relative_time",
        lambda _timestamp: "4m ago",
    )

    async with AcePage(
        query='"visual"',
        size=(120, 40),
        changespecs=changespecs(),
    ) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(NotificationModal([notification]))
        await page.expect_modal("NotificationModal")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Agent Question")
        assert_page_svg_contains(page, "Question from")
        assert_page_svg_contains(page, "memory-protection")
        assert_page_svg_contains(page, "Awaiting your answer")
        assert_page_svg_contains(page, "Protected memory regenerated")
        ace_png_visual.assert_page_png(
            page,
            "notification_question_summary_120x40",
            title="ACE question notification summary",
        )
