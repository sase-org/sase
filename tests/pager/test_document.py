"""Tests for the pager document model and input adapters."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from rich.text import Text

from sase.bead.cli_show_batch import (
    build_show_batch_document,
    render_show_batch,
    resolve_show_batch,
)
from sase.bead.cli_detail_style import DetailStyle
from sase.bead.model import Issue, IssueType
from sase.pager.adapters import document_from_paths
from sase.pager.document import (
    AttachedTarget,
    PagerDocument,
    PagerOrigin,
    PagerSection,
    section_target_spans,
)


@contextmanager
def _view(issues: dict[str, Issue]) -> Iterator[object]:
    class _View:
        def show(self, issue_id: str) -> Issue:
            try:
                return issues[issue_id]
            except KeyError:
                raise KeyError(issue_id) from None

        def get_epic_children(self, _issue_id: str) -> list[Issue]:
            return []

        def list_issues(self) -> list[Issue]:
            return list(issues.values())

    yield _View()


def test_ansi_body_round_trips_plain_text_and_styles() -> None:
    section = PagerSection(
        identity="file:/tmp/demo.py",
        title="demo.py",
        kind="file",
        body="\x1b[31mred\x1b[0m src/sase/pager/document.py",
    )

    body = section.body_text

    assert section.plain_text == "red src/sase/pager/document.py"
    assert isinstance(section.body_renderable, Text)
    assert body.plain == section.plain_text
    assert body.spans
    assert body.spans[0].start == 0
    assert body.spans[0].end == 3


def test_attached_target_suppresses_overlapping_scanned_span() -> None:
    body = "open src/sase/pager/document.py and https://example.test"
    path_start = body.index("src/")
    path_end = path_start + len("src/sase/pager/document.py")
    section = PagerSection(
        identity="file:/tmp/demo.py",
        title="demo.py",
        kind="file",
        body=body,
        targets=(
            AttachedTarget(
                kind="commit",
                target={"sha": "abcdef1234567890"},
                start=path_start,
                end=path_end,
            ),
        ),
    )

    targets = section_target_spans(section, PagerOrigin.FILE)

    assert [(target.source, target.kind, target.start) for target in targets] == [
        ("attached", "commit", path_start),
        ("scanned", "url", body.index("https://")),
    ]
    assert targets[0].target == {"sha": "abcdef1234567890"}
    assert targets[0].text == "src/sase/pager/document.py"


def test_attached_target_span_must_fit_body() -> None:
    with pytest.raises(ValueError, match="exceeds body length"):
        PagerSection(
            identity="file:/tmp/demo.py",
            title="demo.py",
            kind="file",
            body="short",
            targets=(
                AttachedTarget(kind="file", target="/tmp/demo.py", start=0, end=9),
            ),
        )


def test_path_list_adapter_builds_one_file_section_per_path(tmp_path: Path) -> None:
    first = tmp_path / "first.md"
    second = tmp_path / "second.txt"
    first.write_text("see src/sase/pager/document.py\n", encoding="utf-8")
    second.write_text("plain\n", encoding="utf-8")

    document = document_from_paths(["first.md", second], cwd=tmp_path)

    assert document.title == "2 files"
    assert document.origin is PagerOrigin.FILE
    assert [section.title for section in document.sections] == [
        "first.md",
        str(second),
    ]
    assert [section.identity for section in document.sections] == [
        f"file:{first.resolve()}",
        f"file:{second.resolve()}",
    ]
    assert [section.plain_text for section in document.sections] == [
        "see src/sase/pager/document.py\n",
        "plain\n",
    ]


def test_bead_show_batch_adapter_matches_single_bead_rendering() -> None:
    issue = Issue(id="sase-1", title="First", issue_type=IssueType.TASK)
    with _view({issue.id: issue}) as view:
        batch = resolve_show_batch(
            view,
            [issue.id],
            format_name="full",
            include_links=True,
        )

    document = build_show_batch_document(
        batch,
        style=DetailStyle.PLAIN,
        wrap=80,
        relativize_design=False,
        plan_roots=(),
        reference_context_factory=lambda: None,
        creator_url_for=lambda _name: None,
        page_url_for=lambda _id: None,
    )
    expected_body = render_show_batch(
        batch,
        format_name="full",
        include_links=True,
        style=DetailStyle.PLAIN,
        wrap=80,
        relativize_design=False,
        plan_roots=(),
        reference_context_factory=lambda: None,
        creator_url_for=lambda _name: None,
        page_url_for=lambda _id: None,
    )
    expected = PagerDocument(
        sections=(
            PagerSection(
                identity="bead:sase-1",
                title="sase-1 · First",
                kind="bead",
                body=expected_body,
                subject_ref="bead:sase-1",
            ),
        ),
        title="sase-1 · First",
        origin=PagerOrigin.BEAD,
    )

    assert document == expected


def test_bead_show_batch_adapter_uses_one_section_per_bead() -> None:
    issues = {
        "sase-1": Issue(id="sase-1", title="First", issue_type=IssueType.TASK),
        "sase-2": Issue(id="sase-2", title="Second", issue_type=IssueType.TASK),
    }
    with _view(issues) as view:
        batch = resolve_show_batch(
            view,
            ["sase-1", "sase-2"],
            format_name="full",
            include_links=True,
        )

    document = build_show_batch_document(
        batch,
        style=DetailStyle.PLAIN,
        wrap=80,
        relativize_design=False,
        plan_roots=(),
        reference_context_factory=lambda: None,
        creator_url_for=lambda _name: None,
        page_url_for=lambda _id: None,
    )

    assert document.title == "2 beads"
    assert [
        (section.identity, section.subject_ref) for section in document.sections
    ] == [
        ("bead:sase-1", "bead:sase-1"),
        ("bead:sase-2", "bead:sase-2"),
    ]
    assert all("── 1/2 " not in section.plain_text for section in document.sections)
