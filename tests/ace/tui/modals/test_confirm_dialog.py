"""Tests for shared confirmation dialog rendering helpers."""

from __future__ import annotations

from rich.text import Text

from sase.ace.tui.modals.confirm_dialog import ConfirmDialog, ConfirmKind


def _styled_segments(text: Text) -> list[tuple[str, str]]:
    return [(text.plain[span.start : span.end], str(span.style)) for span in text.spans]


def test_styled_subject_text_colors_agent_list_semantics() -> None:
    modal = ConfirmDialog(
        "Dismiss Completed Agents",
        "Dismiss these completed agents?",
        subject=(
            "Dismiss: 2 sase agents\n  sase @research.0s.cld\n  sase @research.0s.cdx"
        ),
        kind=ConfirmKind.DANGER,
    )

    text = modal._styled_subject_text()

    assert text.plain == (
        "Dismiss: 2 sase agents\n› sase @research.0s.cld\n› sase @research.0s.cdx"
    )
    segments = _styled_segments(text)
    assert ("Dismiss:", "bold yellow") in segments
    assert ("2", "bold red") in segments
    assert (" sase agents", "dim white") in segments
    assert ("› ", "red") in segments
    assert ("sase", "bold green") in segments
    assert ("@", "dim white") in segments
    assert ("research.0s.cld", "bold cyan") in segments
    assert ("research.0s.cdx", "bold cyan") in segments


def test_styled_subject_text_uses_single_line_fallback() -> None:
    modal = ConfirmDialog(
        "Commit & Push",
        "Commit and push your saved changes?",
        subject="xprompts/review.md",
        kind=ConfirmKind.NEUTRAL,
    )

    text = modal._styled_subject_text()

    assert text.plain == "xprompts/review.md"
    assert _styled_segments(text) == [("xprompts/review.md", "cyan")]


def test_styled_subject_header_without_count_degrades_gracefully() -> None:
    modal = ConfirmDialog(
        "Kill & Dismiss All",
        "Kill running agents and dismiss completed agents?",
        subject="running: visual.worker, visual.indexer",
        kind=ConfirmKind.DANGER,
    )

    text = modal._styled_subject_text()

    assert text.plain == "running: visual.worker, visual.indexer"
    assert ("running:", "bold yellow") in _styled_segments(text)
    assert (" visual.worker, visual.indexer", "yellow") in _styled_segments(text)
