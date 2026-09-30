"""Regression: bead-show attachment spans use plain-text coordinates.

``build_show_batch_document`` with ``DetailStyle.RICH`` renders ANSI escapes,
so attachment spans computed against the raw body exceed the plain length and
``PagerSection`` raises ``ValueError``. Spans must be computed against
``section.plain_text`` so both styles cover exactly ``[<name>]`` or ``<name>``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest

from sase.bead.cli_detail_style import DetailStyle
from sase.bead.cli_show_batch import (
    build_show_batch_document,
    default_show_render_context_resolver,
    resolve_show_batch,
)
from sase.bead.model import (
    BeadNote,
    BeadNoteAttachment,
    Issue,
    IssueType,
    Status,
    TaskPlusOneEvidence,
)

_DIGEST = "ab" * 32
_NOTE_NAME = "trace.log"
_EVIDENCE_NAME = "shot.png"
_ISSUE_ID = "sase-zz.9"


def _descriptor(name: str, mime_type: str) -> BeadNoteAttachment:
    return BeadNoteAttachment(
        name=name, sha256=_DIGEST, size_bytes=8, mime_type=mime_type
    )


def _issue() -> Issue:
    description = "\n\n".join(
        f"Paragraph {index} with enough styled content to shift ANSI offsets."
        for index in range(20)
    )
    notes = [
        BeadNote(
            id=f"e{index}",
            timestamp="2026-09-30T00:00:00Z",
            author="tester",
            text=f"Filler note {index} with some content. " * 10,
            attachments=(),
        )
        for index in range(5)
    ]
    notes.append(
        BeadNote(
            id="eX",
            timestamp="2026-09-30T00:00:00Z",
            author="tester",
            text=f"see @attachment:{_NOTE_NAME}",
            attachments=(_descriptor(_NOTE_NAME, "text/plain"),),
        )
    )
    return Issue(
        id=_ISSUE_ID,
        title="Span target",
        status=Status.OPEN,
        issue_type=IssueType.TASK,
        description=description,
        notes=notes,
        plus_one_evidence=[
            TaskPlusOneEvidence(
                timestamp="2026-09-30T00:00:00Z",
                reporter="reviewer",
                note=f"confirmed via @attachment:{_EVIDENCE_NAME}",
                attachments=(_descriptor(_EVIDENCE_NAME, "image/png"),),
            )
        ],
    )


@contextmanager
def _view(issues: dict[str, Issue]) -> Iterator[object]:
    class _InMemoryView:
        def show(self, issue_id: str) -> Issue:
            return issues[issue_id]

        def get_epic_children(self, _issue_id: str) -> list[Issue]:
            return []

        def list_issues(self) -> list[Issue]:
            return list(issues.values())

    yield _InMemoryView()


_render_context = default_show_render_context_resolver(
    design_paths_are_relative_fn=lambda: False,
    plan_reference_roots_fn=lambda: (),
    artifact_reference_context_fn=lambda: None,
    resolve_bead_creator_url_fn=lambda _name: None,
    resolve_bead_page_url_fn=lambda _id: None,
)


@pytest.mark.parametrize("style", [DetailStyle.PLAIN, DetailStyle.RICH])
def test_attachment_spans_cover_chips_in_both_styles(
    tmp_path, monkeypatch: pytest.MonkeyPatch, style: DetailStyle
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    issue = _issue()
    with _view({issue.id: issue}) as view:
        batch = resolve_show_batch(
            view, [issue.id], format_name="full", include_links=False
        )
    document = build_show_batch_document(
        batch, style=style, wrap=80, render_context_for=_render_context
    )
    section = document.sections[0]
    names = [_NOTE_NAME, _EVIDENCE_NAME]
    for name in names:
        matches = [
            target
            for target in section.targets
            if str(target.target) == f"attachment:{issue.id}/{name}"
        ]
        assert matches, f"missing span for {name} under {style}"
        assert all(target.kind == "artifact_ref" for target in matches)
    for target in section.targets:
        if not str(target.target).startswith("attachment:"):
            continue
        sliced = section.plain_text[target.start : target.end]
        assert sliced in {f"[{name}]" for name in names} | set(names), (
            f"{sliced!r} covers no chip under {style}"
        )


def test_attachment_names_for_issue_covers_notes_and_evidence() -> None:
    from sase.bead.show_images import attachment_names_for_issue

    assert attachment_names_for_issue(_issue()) == [_NOTE_NAME, _EVIDENCE_NAME]
