"""Failed-agent rendering in typed ``#fork`` history assembly."""

from __future__ import annotations

from pathlib import Path

from sase.history.chat import build_fork_injected_history
from tests._fork_history_helpers import write_chat


def test_single_failed_agent_source_marks_failure_and_keeps_transcript(
    tmp_path: Path,
) -> None:
    chat = tmp_path / "failed.md"
    write_chat(chat, "Fix the parser", "")

    rendered = build_fork_injected_history(
        [
            {
                "kind": "agent",
                "name": "alpha",
                "path": str(chat),
                "failure": {
                    "outcome": "failed",
                    "error": "RuntimeError: boom",
                    "traceback": "Traceback\nRuntimeError: boom",
                    "ended_at": "2026-08-24 15:04:05 EDT",
                    "transcript_available": True,
                },
            }
        ]
    )

    assert "# Previous Conversation — PARENT AGENT FAILED" in rendered
    assert "parent agent `alpha` did not finish" in rendered
    assert "- **Outcome:** `failed`" in rendered
    assert "- **Ended:** `2026-08-24 15:04:05 EDT`" in rendered
    assert "RuntimeError: boom" in rendered
    assert "**Traceback (last 20 lines):**" in rendered
    assert "Fix the parser" in rendered
    assert (
        "**End of transcript — agent `alpha` failed here: `RuntimeError: boom`.**"
    ) in rendered


def test_failed_traceback_renders_tail_and_truncation_marker(tmp_path: Path) -> None:
    chat = tmp_path / "failed.md"
    write_chat(chat, "Run tests", "")
    traceback = "\n".join(f"line {index:02d}" for index in range(25))

    rendered = build_fork_injected_history(
        [
            {
                "kind": "agent",
                "name": "alpha",
                "path": str(chat),
                "failure": {
                    "outcome": "failed",
                    "error": "boom",
                    "traceback": traceback,
                    "transcript_available": True,
                },
            }
        ]
    )

    assert "line 04" not in rendered
    assert "line 05" in rendered
    assert "line 24" in rendered
    assert "… (truncated)" in rendered


def test_failed_source_missing_error_or_traceback_degrades(tmp_path: Path) -> None:
    chat = tmp_path / "failed.md"
    write_chat(chat, "Investigate", "")

    rendered = build_fork_injected_history(
        [
            {
                "kind": "agent",
                "name": "alpha",
                "path": str(chat),
                "failure": {
                    "outcome": "failed",
                    "transcript_available": True,
                },
            }
        ]
    )

    assert "_(none recorded)_" in rendered
    assert "**Traceback (last 20 lines):**" not in rendered
    assert "failed here: `outcome failed`" in rendered


def test_failed_source_without_transcript_quotes_launch_prompt() -> None:
    rendered = build_fork_injected_history(
        [
            {
                "kind": "agent",
                "name": "alpha",
                "path": "",
                "failure": {
                    "outcome": "failed",
                    "error": "launch crashed",
                    "transcript_available": False,
                    "launch_prompt": "Implement the change\nThen verify it",
                },
            }
        ]
    )

    assert "_No transcript was saved" in rendered
    assert "**Assistant:**" not in rendered
    assert "> Implement the change" in rendered
    assert "> Then verify it" in rendered


def test_multi_agent_failed_parent_marks_only_that_section(
    tmp_path: Path,
) -> None:
    good_chat = tmp_path / "good.md"
    bad_chat = tmp_path / "bad.md"
    write_chat(good_chat, "Good prompt", "Good reply")
    write_chat(bad_chat, "Bad prompt", "")

    rendered = build_fork_injected_history(
        [
            {"kind": "agent", "name": "good", "path": str(good_chat)},
            {
                "kind": "agent",
                "name": "bad",
                "path": str(bad_chat),
                "failure": {
                    "outcome": "failed",
                    "error": "ValueError: bad",
                    "transcript_available": True,
                },
            },
        ]
    )

    assert "## Conversation 1 of 2 — agent `good` (FAILED)" not in rendered
    assert "## Conversation 2 of 2 — agent `bad` (FAILED)" in rendered
    assert "One or more parent sections are marked FAILED" in rendered
    assert "ValueError: bad" in rendered
    assert "Good reply" in rendered
