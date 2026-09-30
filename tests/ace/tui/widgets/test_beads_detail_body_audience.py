"""TUI beads-pane detail body carries descriptor audience badges.

The shared bead presentation never stats a store: each attachment line
shows ``🌐`` for explicit public and ``🔒`` otherwise, straight from the
descriptor's visibility.
"""

from __future__ import annotations

from sase.ace.tui.widgets.artifacts.beads_detail_body import (
    note_markdown,
    plus_one_evidence_markdown,
)
from sase.bead.model import (
    BeadNote,
    BeadNoteAttachment,
    Issue,
    IssueType,
    Status,
    TaskPlusOneEvidence,
)


def _attachment(
    name: str,
    digest: str,
    *,
    visibility: str | None = None,
) -> BeadNoteAttachment:
    return BeadNoteAttachment(
        name=name,
        sha256=digest,
        size_bytes=8,
        mime_type="text/plain",
        visibility=visibility,
    )


def _issue(
    *notes: tuple[str, tuple[BeadNoteAttachment, ...]],
    evidence: tuple[TaskPlusOneEvidence, ...] = (),
) -> Issue:
    return Issue(
        id="sase-1d5.7",
        title="tui audience chips",
        status=Status.OPEN,
        issue_type=IssueType.TASK,
        notes=tuple(
            BeadNote(
                id=f"e{index}",
                timestamp="2026-09-30T00:00:00Z",
                author="tester",
                text=text,
                attachments=manifest,
            )
            for index, (text, manifest) in enumerate(notes, start=1)
        ),
        plus_one_evidence=list(evidence),
    )


def test_note_attachments_show_descriptor_audience() -> None:
    issue = _issue(
        (
            "mixed @attachment:pub.txt and @attachment:priv.txt",
            (
                _attachment("pub.txt", "aa" * 32, visibility="public"),
                _attachment("priv.txt", "bb" * 32, visibility="private"),
                _attachment("old.bin", "cc" * 32),
            ),
        )
    )
    body = "\n".join(note_markdown(issue))
    assert "- 🌐 pub.txt" in body
    assert "- 🔒 priv.txt" in body
    # Absent visibility (pre-visibility descriptors) renders private.
    assert "- 🔒 old.bin" in body


def test_plus_one_evidence_shows_descriptor_audience() -> None:
    issue = _issue(
        ("plain", ()),
        evidence=(
            TaskPlusOneEvidence(
                timestamp="2026-09-30T00:00:00Z",
                reporter="tester",
                note="shots @attachment:pub.png",
                attachments=(
                    _attachment("pub.png", "dd" * 32, visibility="public"),
                    _attachment("secret.png", "ee" * 32, visibility="private"),
                ),
            ),
        ),
    )
    body = "\n".join(plus_one_evidence_markdown(issue))
    assert "🌐 pub.png" in body
    assert "🔒 secret.png" in body
