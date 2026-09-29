"""Cached attachment views for the Beads open-attachments key."""

from __future__ import annotations

from sase.ace.tui.widgets.artifacts.beads_attachment_views import (
    cached_attachment_view_paths,
)
from sase.bead.model import BeadNote, BeadNoteAttachment, Issue, IssueType


def _issue_with_notes(*notes: BeadNote) -> Issue:
    issue = Issue(id="alpha-1", title="Bead", issue_type=IssueType.TASK)
    issue.notes = list(notes)
    return issue


def test_empty_issue_has_no_cached_views() -> None:
    assert cached_attachment_view_paths(_issue_with_notes()) == ()


def test_uncached_attachments_are_skipped(monkeypatch) -> None:
    import sase.bead.attachment_presentation as presentation

    monkeypatch.setattr(
        presentation, "attachment_availability", lambda _sha: "unavailable"
    )
    issue = _issue_with_notes(
        BeadNote(
            id="note-1",
            timestamp="2026-07-07T12:00:00Z",
            author="agent.alpha",
            text="See @attachment:missing.png",
            attachments=(
                BeadNoteAttachment(
                    name="missing.png",
                    sha256="ab" * 32,
                    size_bytes=10,
                    mime_type="image/png",
                ),
            ),
        )
    )

    assert cached_attachment_view_paths(issue) == ()


def test_cached_views_dedup_by_name(monkeypatch, tmp_path) -> None:
    import sase.bead.attachment_presentation as presentation

    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    first.write_bytes(b"a")
    second.write_bytes(b"b")
    monkeypatch.setattr(presentation, "attachment_availability", lambda _sha: "cached")
    monkeypatch.setattr(
        presentation,
        "attachment_view_path",
        lambda sha, _name: str(first if sha.startswith("aa") else second),
    )
    issue = _issue_with_notes(
        BeadNote(
            id="note-1",
            timestamp="2026-07-07T12:00:00Z",
            author="agent.alpha",
            text="First @attachment:dup.png",
            attachments=(
                BeadNoteAttachment(
                    name="dup.png",
                    sha256="aa" + "0" * 62,
                    size_bytes=1,
                    mime_type="image/png",
                ),
            ),
        ),
        BeadNote(
            id="note-2",
            timestamp="2026-07-07T13:00:00Z",
            author="agent.alpha",
            text="Second @attachment:dup.png",
            attachments=(
                BeadNoteAttachment(
                    name="dup.png",
                    sha256="bb" + "0" * 62,
                    size_bytes=1,
                    mime_type="image/png",
                ),
            ),
        ),
    )

    assert cached_attachment_view_paths(issue) == (first,)
