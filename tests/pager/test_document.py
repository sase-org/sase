"""Tests for the pager document model and input adapters."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from rich.text import Text

from sase.artifact_ref_models import (
    ArtifactRefContext,
    ArtifactRefDocumentRoot,
    ArtifactRefDocumentTarget,
    ArtifactRefProject,
    ArtifactRefSpan,
)
from sase.bead.cli_show_batch import (
    _ShowRenderContext,
    _show_entry_link_anchors,
    build_show_batch_document,
    default_show_render_context_resolver,
    render_show_batch,
    resolve_show_batch,
)
from sase.bead.cli_detail_style import DetailStyle
from sase.bead.model import BeadNote, Issue, IssueType
from sase.pager.adapters import document_from_paths
from sase.pager.document import (
    AttachedTarget,
    PagerDocument,
    PagerOrigin,
    PagerSection,
    PagerTargetSpan,
    RawSourceSpec,
    section_syntax_language,
    section_target_spans,
    target_action_destination,
    target_resolution_cache_identity,
)
from sase.pager.link_context import LinkAnchor
from sase.pager.link_scan import LinkSpanKind


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


def test_string_body_keeps_a_single_trailing_newline() -> None:
    section = PagerSection(
        identity="file:/tmp/demo.txt",
        title="demo.txt",
        kind="file",
        body="indexed\n",
    )
    assert section.plain_text == "indexed\n"


def test_string_body_preserves_double_trailing_newline() -> None:
    section = PagerSection(
        identity="file:/tmp/demo.txt",
        title="demo.txt",
        kind="file",
        body="indexed\n\n",
    )
    assert section.plain_text == "indexed\n\n"


def test_string_body_does_not_double_trailing_newline_when_from_ansi_keeps_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def keep_trailing(text: str, *_args: object, **_kwargs: object) -> Text:
        result = Text(text.rstrip("\n"))
        if text.endswith("\n"):
            result.append("\n")
        return result

    monkeypatch.setattr(Text, "from_ansi", staticmethod(keep_trailing))
    section = PagerSection(
        identity="file:/tmp/demo.txt",
        title="demo.txt",
        kind="file",
        body="indexed\n",
    )
    assert section.plain_text == "indexed\n"


def test_raw_source_defaults_to_none_and_does_not_affect_rendering() -> None:
    section = PagerSection(
        identity="file:/tmp/demo.py",
        title="demo.py",
        kind="file",
        body="print('hi')\n",
    )
    assert section.raw_source is None
    assert section_syntax_language(section) is None


def test_section_syntax_language_returns_the_spec_language_when_eligible() -> None:
    section = PagerSection(
        identity="file:/tmp/demo.py",
        title="demo.py",
        kind="file",
        body="print('hi')\n",
        raw_source=RawSourceSpec(language="python"),
    )
    assert section_syntax_language(section) == "python"


def test_section_syntax_language_is_none_when_ineligible() -> None:
    section = PagerSection(
        identity="file:/tmp/demo.py",
        title="demo.py",
        kind="file",
        body="print('hi')\n",
        raw_source=RawSourceSpec(language="python", eligible=False),
    )
    assert section_syntax_language(section) is None


def test_section_syntax_language_is_none_without_a_language_hint() -> None:
    section = PagerSection(
        identity="file:/tmp/demo.txt",
        title="demo.txt",
        kind="file",
        body="plain text\n",
        raw_source=RawSourceSpec(language=None),
    )
    assert section_syntax_language(section) is None


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
    assert document.link_context is not None
    assert document.link_context.base_dirs[0] == Path.cwd().resolve()
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
    assert [section.link_anchors[0].directory for section in document.sections] == [
        tmp_path.resolve(),
        tmp_path.resolve(),
    ]


def test_path_list_adapter_freezes_context_known_kinds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "note.md"
    source.write_text("see designs:202609/spec.md\n", encoding="utf-8")
    designs = tmp_path / "designs"
    context = ArtifactRefContext(
        document_roots=(ArtifactRefDocumentRoot("designs", designs),),
        chats_root=tmp_path / "chats",
        artifact_index_path=tmp_path / "artifacts" / "index.jsonl",
        repositories=(),
        projects=(ArtifactRefProject(name="demo", key="gh_demo__repo"),),
    )

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "sase.artifact_ref_context.artifact_ref_context",
        lambda *_args, **_kwargs: context,
    )

    document = document_from_paths([source], cwd=tmp_path)
    spans = section_target_spans(document.sections[0], document.origin)

    assert "designs" in document.sections[0].known_kinds
    assert [(span.kind, span.text, span.target) for span in spans] == [
        (
            LinkSpanKind.ARTIFACT_REF.value,
            "designs:202609/spec.md",
            "designs:202609/spec.md",
        )
    ]


_SOURCE_SPAN = ArtifactRefSpan(0, 5)


def _semantic_target(**overrides: object) -> ArtifactRefDocumentTarget:
    values: dict[str, object] = {
        "schema_version": 1,
        "target_kind": "file_path",
        "text": "guide",
        "target": "docs/a.md",
        "well_formed": True,
        "source_span": _SOURCE_SPAN,
        "candidate_span": _SOURCE_SPAN,
        "target_span": _SOURCE_SPAN,
        "label_span": None,
        "destination_span": None,
        "reference_label": None,
        "markdown_destination": None,
        "hosted_destination": None,
        "artifact_reference": None,
        "quoted": False,
    }
    values.update(overrides)
    return ArtifactRefDocumentTarget(**values)  # type: ignore[arg-type]


def _scanned_span(
    kind: LinkSpanKind,
    *,
    text: str = "guide",
    target: str,
    semantic: ArtifactRefDocumentTarget,
) -> PagerTargetSpan:
    return PagerTargetSpan(
        kind=kind.value,
        target=target,
        start=0,
        end=len(text),
        text=text,
        source="scanned",
        semantic_target=semantic,
    )


def test_equal_visible_labels_keep_distinct_action_destinations() -> None:
    markdown = _scanned_span(
        LinkSpanKind.FILE_PATH,
        target="guide",
        semantic=_semantic_target(
            target="docs/a.md",
            markdown_destination="docs/a.md",
        ),
    )
    artifact = _scanned_span(
        LinkSpanKind.ARTIFACT_REF,
        target="guide",
        semantic=_semantic_target(
            target_kind="artifact_ref",
            target="plan:a.md",
            artifact_reference="plan:a.md",
            reference_label="2",
        ),
    )
    hosted = _scanned_span(
        LinkSpanKind.URL,
        target="guide",
        semantic=_semantic_target(
            target_kind="url",
            target="https://example.test/a.md",
            hosted_destination="https://example.test/a.md",
            reference_label="2",
        ),
    )
    other_markdown = _scanned_span(
        LinkSpanKind.FILE_PATH,
        target="guide",
        semantic=_semantic_target(
            target="docs/b.md",
            markdown_destination="docs/b.md",
        ),
    )

    assert markdown.text == artifact.text == hosted.text == other_markdown.text
    assert target_action_destination(markdown, PagerOrigin.FILE) == "docs/a.md"
    assert target_action_destination(artifact, PagerOrigin.FILE) == "plan:a.md"
    assert (
        target_action_destination(hosted, PagerOrigin.FILE)
        == "https://example.test/a.md"
    )
    assert target_action_destination(other_markdown, PagerOrigin.FILE) == "docs/b.md"
    assert target_resolution_cache_identity(
        markdown, PagerOrigin.FILE
    ) != target_resolution_cache_identity(other_markdown, PagerOrigin.FILE)
    assert target_resolution_cache_identity(
        artifact, PagerOrigin.FILE
    ) != target_resolution_cache_identity(hosted, PagerOrigin.FILE)


def test_bead_show_freezes_kinds_for_note_refs_when_issue_has_no_refs(
    tmp_path: Path,
) -> None:
    designs = tmp_path / "designs"
    designs.mkdir()
    context = ArtifactRefContext(
        document_roots=(ArtifactRefDocumentRoot("designs", designs),),
        chats_root=tmp_path / "chats",
        artifact_index_path=tmp_path / "artifacts" / "index.jsonl",
        repositories=(),
        projects=(ArtifactRefProject(name="demo", key="gh_demo__repo"),),
    )
    issue = Issue(
        id="sase-1",
        title="First",
        issue_type=IssueType.TASK,
        notes=[
            BeadNote(
                id="note-1",
                timestamp="2026-01-01T00:00:00Z",
                author="tester",
                text="see designs:202609/spec.md",
            )
        ],
    )
    assert issue.refs == []
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
        render_context_for=default_show_render_context_resolver(
            design_paths_are_relative_fn=lambda: False,
            plan_reference_roots_fn=lambda: (),
            artifact_reference_context_fn=lambda: context,
            resolve_bead_creator_url_fn=lambda _name: None,
            resolve_bead_page_url_fn=lambda _id: None,
        ),
    )
    section = document.sections[0]
    spans = section_target_spans(section, document.origin)

    assert "designs" in section.known_kinds
    assert "designs:202609/spec.md" in section.plain_text
    assert (
        LinkSpanKind.ARTIFACT_REF.value,
        "designs:202609/spec.md",
    ) in [(span.kind, span.target) for span in spans]


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
        render_context_for=_plain_render_context,
    )
    expected_body = render_show_batch(
        batch,
        format_name="full",
        include_links=True,
        style=DetailStyle.PLAIN,
        wrap=80,
        render_context_for=_plain_render_context,
    )
    section = document.sections[0]
    assert document.title == "sase-1 · First"
    assert document.origin is PagerOrigin.BEAD
    assert section.identity == "bead:sase-1"
    assert section.subject_ref == "bead:sase-1"
    assert section.origin is PagerOrigin.BEAD
    assert section.plain_text == expected_body


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
        render_context_for=_plain_render_context,
    )

    assert document.title == "2 beads"
    assert [
        (section.identity, section.subject_ref) for section in document.sections
    ] == [
        ("bead:sase-1", "bead:sase-1"),
        ("bead:sase-2", "bead:sase-2"),
    ]
    assert all("── 1/2 " not in section.plain_text for section in document.sections)


def test_bead_show_section_anchors_to_entry_primary_workspace(
    tmp_path: Path,
) -> None:
    context = _ShowRenderContext(
        relativize_design=False,
        plan_roots=(),
        design_cwd=tmp_path,
        reference_context_factory=lambda: None,
        creator_url_for=lambda _name: None,
        page_url_for=lambda _id: None,
    )

    assert _show_entry_link_anchors(context) == (
        LinkAnchor(directory=tmp_path.resolve(), workspace_num=1),
    )


_plain_render_context = default_show_render_context_resolver(
    design_paths_are_relative_fn=lambda: False,
    plan_reference_roots_fn=lambda: (),
    artifact_reference_context_fn=lambda: None,
    resolve_bead_creator_url_fn=lambda _name: None,
    resolve_bead_page_url_fn=lambda _id: None,
)
