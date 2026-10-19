"""Memoization, prefix, and local-anchor tests for the pager document model."""

from __future__ import annotations

from sase.pager._syntax_cache import content_digest
from sase.pager.document import (
    AttachedTarget,
    PagerOrigin,
    PagerSection,
    PagerTargetSpan,
    section_content_digest,
    section_line_prefix,
    section_target_spans,
    section_with_bead_id_prefixes,
)
from sase.pager.link_scan import LinkSpanKind


def _memo_section(body: str = "see src/demo.py:12\nsecond line\n") -> PagerSection:
    return PagerSection(
        identity="file:/tmp/memo.py",
        title="memo.py",
        kind="file",
        body=body,
    )


def test_section_target_spans_are_memoized_per_section_and_origin() -> None:
    """Repeat lookups return the cached merge; origins key separately."""
    section = _memo_section()

    first = section_target_spans(section, PagerOrigin.FILE)
    assert section_target_spans(section, PagerOrigin.FILE) is first

    other = section_target_spans(section, PagerOrigin.BEAD)
    assert other is not first
    assert section_target_spans(section, PagerOrigin.BEAD) is other
    # A section with its own origin ignores the passed origin for the key.
    pinned = PagerSection(
        identity="bead:sase-1",
        title="sase-1",
        kind="bead",
        body="sase-1\n",
        origin=PagerOrigin.BEAD,
    )
    assert section_target_spans(pinned, PagerOrigin.FILE) is section_target_spans(
        pinned, PagerOrigin.DIFF
    )


def test_section_content_digest_matches_and_memoizes() -> None:
    """The memoized digest equals a fresh digest of the plain text."""
    section = _memo_section()

    assert section_content_digest(section) == content_digest(section.plain_text)
    assert section_content_digest(section) == section_content_digest(section)


def test_section_line_prefix_matches_per_line_estimates() -> None:
    """Each prefix row equals the direct offset walk at that line start."""
    from sase.pager._labels import _row_for_character_offset

    section = _memo_section("alpha\n" + "x" * 100 + "\n日本語🎉\n")
    starts, rows = section_line_prefix(section, 20)

    assert section_line_prefix(section, 20) == (starts, rows)
    assert len(starts) == len(rows)
    for start, row in zip(starts, rows, strict=True):
        assert _row_for_character_offset(section.plain_text, start, 20) == row


def test_section_line_prefix_bounds_distinct_widths() -> None:
    """Width oscillation cannot grow the per-section prefix memo."""
    section = _memo_section()

    for width in (10, 20, 30, 40, 50, 60):
        section_line_prefix(section, width)

    widths = [key for key in section._memo if key[0] == "rows"]
    assert len(widths) <= 4


def test_pager_section_bead_id_prefixes_normalize() -> None:
    section = PagerSection(
        identity="bead:bob-cli-1",
        title="bob-cli-1",
        kind="bead",
        body="bob-cli-1\n",
        bead_id_prefixes=("bob-cli", "bob-cli", "a.b", " "),
    )
    assert section.bead_id_prefixes == ("bob-cli",)


def test_section_target_spans_honors_bead_id_prefixes() -> None:
    body = "see bob-cli-5s.1 and sase-uk.1 here"
    bob_only = PagerSection(
        identity="bead:bob-cli-5s",
        title="bob-cli-5s",
        kind="bead",
        body=body,
        bead_id_prefixes=("bob-cli",),
    )
    both = PagerSection(
        identity="bead:bob-cli-5s",
        title="bob-cli-5s",
        kind="bead",
        body=body,
        bead_id_prefixes=("bob-cli", "sase"),
    )
    default = PagerSection(
        identity="bead:bob-cli-5s", title="bob-cli-5s", kind="bead", body=body
    )
    assert [span.text for span in section_target_spans(bob_only, PagerOrigin.BEAD)] == [
        "bob-cli-5s.1"
    ]
    assert [span.text for span in section_target_spans(both, PagerOrigin.BEAD)] == [
        "bob-cli-5s.1",
        "sase-uk.1",
    ]
    assert [span.text for span in section_target_spans(default, PagerOrigin.BEAD)] == [
        "sase-uk.1"
    ]


def test_section_with_bead_id_prefixes_returns_same_object_for_equal() -> None:
    section = PagerSection(
        identity="bead:bob-cli-5s",
        title="bob-cli-5s",
        kind="bead",
        body="bob-cli-5s.1\n",
        bead_id_prefixes=("bob-cli",),
    )
    assert section_with_bead_id_prefixes(section, ("bob-cli", "bob-cli")) is section


def test_section_with_bead_id_prefixes_returns_copy_with_fresh_spans() -> None:
    section = PagerSection(
        identity="bead:bob-cli-5s",
        title="bob-cli-5s",
        kind="bead",
        body="see bob-cli-5s.1 here",
    )
    before = section_target_spans(section, PagerOrigin.BEAD)
    assert [span.text for span in before] == []
    stamped = section_with_bead_id_prefixes(section, ("bob-cli",))
    assert stamped is not section
    assert stamped.bead_id_prefixes == ("bob-cli",)
    assert stamped.plain_text == section.plain_text
    after = section_target_spans(stamped, PagerOrigin.BEAD)
    assert [span.text for span in after] == ["bob-cli-5s.1"]
    assert [span.text for span in section_target_spans(section, PagerOrigin.BEAD)] == []


def _anchor_section(body: str) -> PagerSection:
    return PagerSection(
        identity="file:/tmp/anchors.md",
        title="anchors.md",
        kind="file",
        body=body,
    )


def _first_file_path_span(
    section: PagerSection, origin: PagerOrigin
) -> PagerTargetSpan:
    from sase.pager.document import section_target_spans as _spans

    for span in _spans(section, origin):
        if span.kind == LinkSpanKind.FILE_PATH.value:
            return span
    raise AssertionError("no file_path span found")


def test_local_anchor_fragment_classifies_targets() -> None:
    from sase.pager.document import local_anchor_fragment as _frag

    section = _anchor_section("see [x](#slug) here\n")
    span = _first_file_path_span(section, PagerOrigin.FILE)
    assert _frag(span) == "slug"

    empty_section = _anchor_section("see [x](#) here\n")
    assert _frag(_first_file_path_span(empty_section, PagerOrigin.FILE)) == ""

    for body in (
        "see [p](#skill/sase_plan) here\n",
        "see [x](other.md#a) here\n",
        "see [x](./#a) here\n",
        "see https://example.test here\n",
    ):
        sec = _anchor_section(body)
        spans = [
            s
            for s in section_target_spans(sec, PagerOrigin.FILE)
            if s.kind != LinkSpanKind.BARE_TOKEN.value
        ]
        assert spans, body
        # Skill spans are macro_skill; file URLs with bases are file_path but
        # must not count as local anchors; plain URLs never do.
        for candidate in spans:
            if candidate.kind == LinkSpanKind.URL.value:
                assert _frag(candidate) is None
            elif candidate.kind == LinkSpanKind.MACRO_SKILL.value:
                assert _frag(candidate) is None
            else:
                assert _frag(candidate) is None, body


def test_local_anchor_fragment_rejects_attached_targets() -> None:
    from sase.pager.document import local_anchor_fragment as _frag

    section = PagerSection(
        identity="file:/tmp/attached.md",
        title="attached.md",
        kind="file",
        body="hello",
        targets=(AttachedTarget(kind="file", target="#slug", start=0, end=5),),
    )
    spans = section_target_spans(section, PagerOrigin.FILE)
    assert len(spans) == 1
    assert spans[0].source == "attached"
    assert _frag(spans[0]) is None


def test_section_local_anchor_lines_line_range_and_memoization(
    monkeypatch,
) -> None:
    import sase.pager.document as _doc

    section = _anchor_section(
        "line one\nline two\nline three\nline four\nline five\nline six\nline seven\n"
    )
    assert _doc.section_local_anchor_lines(section, "L5-L7") == (5, 7)

    calls: list[str] = []
    import sase.pager.markdown_anchors as _anchors

    original = _anchors.build_markdown_anchor_index

    def counting(text: str):
        calls.append(text)
        return original(text)

    monkeypatch.setattr(_anchors, "build_markdown_anchor_index", counting)
    section2 = _anchor_section("# Alpha\nbody\n## Beta\n")
    assert _doc.section_local_anchor_lines(section2, "beta") == (3, 3)
    assert _doc.section_local_anchor_lines(section2, "beta") == (3, 3)
    assert len(calls) == 1
