"""Tests for the pager's precedence-ordered, origin-scoped link scanner."""

from __future__ import annotations

from sase.ace.tui.widgets.prompt_panel._file_path_hints import (
    file_hint_match_span,
    iter_file_path_matches,
)
from sase.ace.tui.widgets.prompt_panel._hint_caps import (
    HINT_TRUNCATION_MESSAGE,
    HintContentBudget,
)
from sase.pager.link_scan import (
    LinkSpanKind,
    PagerOrigin,
    scan_bounded_links,
    scan_links,
)

_SPAN_FIDELITY_FIXTURE = (
    "see src/foo.py:12 and src/bar.py:12:5 and /tmp/baz.py. plus "
    "https://example.com/src/foo.py"
)


def test_artifact_ref_found_at_leading_and_trailing_position() -> None:
    leading = "@bead:sase-uk.1 leads the line"
    spans = scan_links(leading, PagerOrigin.FILE)
    assert spans[0].kind is LinkSpanKind.ARTIFACT_REF
    assert spans[0].text == "@bead:sase-uk.1"
    assert spans[0].target == "bead:sase-uk.1"
    assert leading[spans[0].start : spans[0].end] == "@bead:sase-uk.1"

    trailing = "the line ends with @bead:sase-uk.1"
    spans = scan_links(trailing, PagerOrigin.FILE)
    assert spans[-1].kind is LinkSpanKind.ARTIFACT_REF
    assert spans[-1].text == "@bead:sase-uk.1"
    assert spans[-1].target == "bead:sase-uk.1"
    assert spans[-1].end == len(trailing)


def test_url_found_at_leading_and_trailing_position() -> None:
    leading = "https://example.com/docs leads the line"
    spans = scan_links(leading, PagerOrigin.FILE)
    assert spans[0].kind is LinkSpanKind.URL
    assert spans[0].text == "https://example.com/docs"

    trailing = "the line ends with https://example.com/docs"
    spans = scan_links(trailing, PagerOrigin.FILE)
    assert spans[-1].kind is LinkSpanKind.URL
    assert spans[-1].end == len(trailing)


def test_file_path_found_at_leading_and_trailing_position() -> None:
    leading = "src/sase/pager/link_scan.py leads the line"
    spans = scan_links(leading, PagerOrigin.FILE)
    assert spans[0].kind is LinkSpanKind.FILE_PATH
    assert spans[0].text == "src/sase/pager/link_scan.py"
    assert spans[0].target == "src/sase/pager/link_scan.py"

    trailing = "the line ends with src/sase/pager/link_scan.py"
    spans = scan_links(trailing, PagerOrigin.FILE)
    assert spans[-1].kind is LinkSpanKind.FILE_PATH
    assert spans[-1].end == len(trailing)


def test_url_and_artifact_ref_are_no_longer_swallowed_by_the_path_regex() -> None:
    text = (
        "@bead:sase-uk.1 and https://example.com/docs/path.md "
        "and src/sase/pager/link_scan.py"
    )

    spans = scan_links(text, PagerOrigin.FILE)

    assert [span.kind for span in spans] == [
        LinkSpanKind.ARTIFACT_REF,
        LinkSpanKind.URL,
        LinkSpanKind.FILE_PATH,
    ]
    assert spans[0].text == "@bead:sase-uk.1"
    assert spans[1].text == "https://example.com/docs/path.md"
    assert spans[2].text == "src/sase/pager/link_scan.py"
    # Spans never overlap: each one's text round-trips through the original.
    for span in spans:
        assert text[span.start : span.end] == span.text


def test_bare_bead_id_is_scoped_to_bead_origin() -> None:
    text = "children sase-uk.1 and sase-uk.2 are phases of sase-uk"

    bead_spans = scan_links(text, PagerOrigin.BEAD)
    bare_tokens = [
        span.text for span in bead_spans if span.kind is LinkSpanKind.BARE_TOKEN
    ]
    assert bare_tokens == ["sase-uk.1", "sase-uk.2", "sase-uk"]

    research_spans = scan_links(text, PagerOrigin.RESEARCH)
    assert research_spans == ()


def test_bare_bead_id_does_not_double_count_a_typed_ref() -> None:
    text = "see @bead:sase-uk.1 for the phase"

    spans = scan_links(text, PagerOrigin.BEAD)

    assert len(spans) == 1
    assert spans[0].kind is LinkSpanKind.ARTIFACT_REF


def test_quoted_artifact_ref_resolves_with_decoded_semantic_target() -> None:
    text = 'see @plan:"a b.md"#L3 for details'
    spans = scan_links(text, PagerOrigin.FILE)

    assert len(spans) == 1
    assert spans[0].text == '@plan:"a b.md"#L3'
    assert spans[0].target == "plan:a b.md#L3"
    assert text[spans[0].start : spans[0].end] == spans[0].text


def test_generated_links_table_ref_keeps_artifact_target_and_hosted_url() -> None:
    text = (
        "<!-- sase:links:start -->\n\n"
        "## Links\n\n"
        "| Relation | Artifact | Why |\n"
        "| --- | --- | --- |\n"
        "| implements | [plan:202609/capture_line_edge_cycling.md][2] | screenshot |\n\n"
        "[2]: https://github.com/bobs-org/bob-cli/blob/main/.sase/plans/202609/capture_line_edge_cycling.md\n\n"
        "<!-- sase:links:end -->\n"
    )

    spans = scan_links(text, PagerOrigin.FILE)

    assert [(span.kind, span.text, span.target) for span in spans] == [
        (
            LinkSpanKind.ARTIFACT_REF,
            "[plan:202609/capture_line_edge_cycling.md][2]",
            "plan:202609/capture_line_edge_cycling.md",
        ),
        (
            LinkSpanKind.URL,
            "https://github.com/bobs-org/bob-cli/blob/main/.sase/plans/202609/capture_line_edge_cycling.md",
            "https://github.com/bobs-org/bob-cli/blob/main/.sase/plans/202609/capture_line_edge_cycling.md",
        ),
    ]
    artifact_target = spans[0].semantic_target
    assert artifact_target is not None
    assert artifact_target.artifact_reference == (
        "plan:202609/capture_line_edge_cycling.md"
    )
    assert artifact_target.hosted_destination == (
        "https://github.com/bobs-org/bob-cli/blob/main/.sase/plans/"
        "202609/capture_line_edge_cycling.md"
    )
    assert artifact_target.reference_label == "2"
    url_target = spans[1].semantic_target
    assert url_target is not None
    assert url_target.hosted_destination == spans[1].target


def test_markdown_link_uses_declared_destination_as_target() -> None:
    text = "[not the path](src/sase/pager/link_scan.py:12)"
    spans = scan_links(text, PagerOrigin.FILE)

    assert len(spans) == 1
    assert spans[0].kind is LinkSpanKind.FILE_PATH
    assert spans[0].text == "[not the path](src/sase/pager/link_scan.py:12)"
    assert spans[0].target == "src/sase/pager/link_scan.py:12"
    assert spans[0].semantic_target is not None
    assert (
        spans[0].semantic_target.markdown_destination
        == "src/sase/pager/link_scan.py:12"
    )


def test_scan_links_uses_frozen_known_kinds_for_configured_document_kind() -> None:
    text = "see designs:202609/spec.md"

    default_spans = scan_links(text, PagerOrigin.FILE)
    configured_spans = scan_links(
        text,
        PagerOrigin.FILE,
        known_kinds=("designs",),
    )

    assert [(span.kind, span.text) for span in default_spans] == [
        (LinkSpanKind.FILE_PATH, "202609/spec.md")
    ]
    assert [(span.kind, span.text, span.target) for span in configured_spans] == [
        (
            LinkSpanKind.ARTIFACT_REF,
            "designs:202609/spec.md",
            "designs:202609/spec.md",
        )
    ]
    assert configured_spans[0].semantic_target is not None
    assert (
        configured_spans[0].semantic_target.artifact_reference
        == "designs:202609/spec.md"
    )


def test_malformed_artifact_candidate_does_not_mask_at_file_path() -> None:
    spans = scan_links("@src/sase/pager/resolve.py:42", PagerOrigin.FILE)

    assert [(span.kind, span.text, span.target) for span in spans] == [
        (
            LinkSpanKind.FILE_PATH,
            "@src/sase/pager/resolve.py:42",
            "src/sase/pager/resolve.py:42",
        )
    ]


def test_diff_origin_recognizes_bare_short_shas() -> None:
    spans = scan_links("commit deadbee1 landed", PagerOrigin.DIFF)

    assert len(spans) == 1
    assert spans[0].kind is LinkSpanKind.BARE_TOKEN
    assert spans[0].text == "deadbee1"


def test_bare_short_sha_is_not_recognized_outside_diff_origin() -> None:
    spans = scan_links("commit deadbee1 landed", PagerOrigin.FILE)

    assert spans == ()


def test_scan_bounded_links_still_shows_truncation_notice() -> None:
    content = "src/head.py " + "src/tail.py " * 50

    result = scan_bounded_links(
        content,
        PagerOrigin.FILE,
        budget=HintContentBudget(
            remaining_bytes=len("src/head.py"), remaining_lines=10
        ),
    )

    assert result.content == "src/head.py"
    assert [span.text for span in result.spans] == ["src/head.py"]
    assert result.notice is not None
    assert HINT_TRUNCATION_MESSAGE in result.notice.plain


def test_scan_bounded_links_reports_no_notice_when_content_fits() -> None:
    result = scan_bounded_links("src/head.py", PagerOrigin.FILE)

    assert result.content == "src/head.py"
    assert result.notice is None


def test_file_path_span_includes_line_and_column_suffixes() -> None:
    text = "open src/foo.py:12 and /tmp/bar.py:12:5"
    spans = [
        span
        for span in scan_links(text, PagerOrigin.FILE)
        if span.kind is LinkSpanKind.FILE_PATH
    ]

    assert [span.text for span in spans] == ["src/foo.py:12", "/tmp/bar.py:12:5"]
    for span in spans:
        assert text[span.start : span.end] == span.text


def test_file_path_span_excludes_a_sentence_ending_dot() -> None:
    text = "open /tmp/notes.py. The end"
    spans = scan_links(text, PagerOrigin.FILE)

    assert [span.text for span in spans] == ["/tmp/notes.py"]
    assert text[spans[0].start : spans[0].end] == "/tmp/notes.py"


def test_file_path_inside_a_url_is_not_a_file_span() -> None:
    text = "see https://example.com/src/foo.py:12 for details"
    spans = scan_links(text, PagerOrigin.FILE)

    assert [span.kind for span in spans] == [LinkSpanKind.URL]
    assert spans[0].text == "https://example.com/src/foo.py:12"


def test_ace_file_path_matcher_output_is_unchanged_on_the_span_fixture() -> None:
    matches = list(iter_file_path_matches(_SPAN_FIDELITY_FIXTURE))
    spans = [file_hint_match_span(match) for match in matches]

    assert [match.group(2) for match in matches] == [
        "src/foo.py",
        "src/bar.py",
        "/tmp/baz.py.",
    ]
    assert [_SPAN_FIDELITY_FIXTURE[start:end] for start, end in spans] == [
        "src/foo.py",
        "src/bar.py",
        "/tmp/baz.py.",
    ]


def test_pager_scan_uses_line_spans_and_drops_sentence_dots_on_fixture() -> None:
    spans = scan_links(_SPAN_FIDELITY_FIXTURE, PagerOrigin.FILE)

    assert [(span.kind, span.text) for span in spans] == [
        (LinkSpanKind.FILE_PATH, "src/foo.py:12"),
        (LinkSpanKind.FILE_PATH, "src/bar.py:12:5"),
        (LinkSpanKind.FILE_PATH, "/tmp/baz.py"),
        (LinkSpanKind.URL, "https://example.com/src/foo.py"),
    ]
    for span in spans:
        assert _SPAN_FIDELITY_FIXTURE[span.start : span.end] == span.text


def test_scan_bounded_links_keeps_line_suffix_spans() -> None:
    result = scan_bounded_links("src/head.py:12", PagerOrigin.FILE)

    assert result.content == "src/head.py:12"
    assert [span.text for span in result.spans] == ["src/head.py:12"]
    assert result.notice is None
