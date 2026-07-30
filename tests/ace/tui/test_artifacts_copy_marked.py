"""Multi-mark coverage for Artifacts copy mode."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.widgets.artifacts.chats_list import ChatRow, chat_row_target
from sase.ace.tui.widgets.artifacts.plans_list import PlanRow, plan_row_target
from tests.ace.tui._artifacts_copy_helpers import CopyHarness


def test_marked_commits_copy_in_visual_order_with_labeled_sections() -> None:
    app = CopyHarness()
    entries = tuple(
        SimpleNamespace(
            repo="sase",
            commit=SimpleNamespace(
                full_id=character * 40,
                short_id=character * 7,
            ),
        )
        for character in ("a", "b")
    )
    targets = tuple(("commit", entry.repo, entry.commit.full_id) for entry in entries)
    app._artifacts_marked_targets = {"commits": set(targets)}
    app.commits_pane = SimpleNamespace(
        result=SimpleNamespace(commits=entries),
        entry_targets=lambda: targets,
    )

    assert app._handle_copy_key("percent_sign") is True

    assert app.copies == [
        (
            "\n".join(
                (
                    "### sase@aaaaaaa",
                    "```",
                    "a" * 40,
                    "```",
                    "### sase@bbbbbbb",
                    "```",
                    "b" * 40,
                    "```",
                )
            ),
            "Copied 2 commit SHAs",
        )
    ]


def test_marked_plans_copy_the_marked_set() -> None:
    app = CopyHarness()
    app.current_artifacts_subtab = "plans"
    rows = tuple(
        PlanRow(
            "proposal",
            f"proposal-{index}",
            "alpha",
            proposal=SimpleNamespace(
                notification=SimpleNamespace(id=f"notice-{index}"),
                plan_path=f"/tmp/plan-{index}.md",
                title=f"Plan {index}",
                body=f"Body {index}",
            ),
        )
        for index in (1, 2)
    )
    targets = tuple(plan_row_target(row) for row in rows)
    app._artifacts_marked_targets = {"plans": set(targets)}
    app.plans_pane = SimpleNamespace(
        _rows={row.row_id: row for row in rows},
        entry_targets=lambda: targets,
    )

    assert app._handle_copy_key("t") is True

    copied, message = app.copies[0]
    assert "### proposal-1\n```\nPlan 1\n```" in copied
    assert "### proposal-2\n```\nPlan 2\n```" in copied
    assert message == "Copied 2 plan titles"


def test_marked_chats_copy_the_marked_set() -> None:
    app = CopyHarness()
    app.current_artifacts_subtab = "chats"
    entries = tuple(
        SimpleNamespace(
            absolute_path=f"/tmp/chat-{index}.md",
            basename=f"chat-{index}",
        )
        for index in (1, 2)
    )
    rows = tuple(
        ChatRow(f"chat-{index}", entry) for index, entry in enumerate(entries, start=1)
    )
    targets = tuple(chat_row_target(row) for row in rows)
    app._artifacts_marked_targets = {"chats": set(targets)}
    app.chats_pane = SimpleNamespace(
        _rows={row.option_id: row for row in rows},
        entry_targets=lambda: targets,
    )

    assert app._handle_copy_key("p") is True

    copied, message = app.copies[0]
    assert "### chat-1\n```\n/tmp/chat-1.md\n```" in copied
    assert "### chat-2\n```\n/tmp/chat-2.md\n```" in copied
    assert message == "Copied 2 chat paths"


def test_marked_bugs_copy_the_marked_set() -> None:
    app = CopyHarness()
    app.current_artifacts_subtab = "bugs"
    issues = tuple(SimpleNamespace(number=number) for number in (41, 42))

    def issue_target(issue: Any) -> tuple[str, ...]:
        return ("bug", "alpha", str(issue.number))

    targets = tuple(issue_target(issue) for issue in issues)
    app._artifacts_marked_targets = {"bugs": set(targets)}
    app.bugs_pane = SimpleNamespace(
        project_scope="alpha",
        issues=issues,
        entry_targets=lambda: targets,
        _issue_target=issue_target,
    )

    assert app._handle_copy_key("b") is True

    copied, message = app.copies[0]
    assert "### #41\n```\n#41\n```" in copied
    assert "### #42\n```\n#42\n```" in copied
    assert message == "Copied 2 issue numbers"
