"""Tests for the pager's precedence-ordered, origin-scoped link scanner."""

from __future__ import annotations

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


def test_artifact_ref_found_at_leading_and_trailing_position() -> None:
    leading = "@bead:sase-uk.1 leads the line"
    spans = scan_links(leading, PagerOrigin.FILE)
    assert spans[0].kind is LinkSpanKind.ARTIFACT_REF
    assert spans[0].text == "@bead:sase-uk.1"
    assert leading[spans[0].start : spans[0].end] == "@bead:sase-uk.1"

    trailing = "the line ends with @bead:sase-uk.1"
    spans = scan_links(trailing, PagerOrigin.FILE)
    assert spans[-1].kind is LinkSpanKind.ARTIFACT_REF
    assert spans[-1].text == "@bead:sase-uk.1"
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
