"""Row-for-row parity between the virtual body model and the composer.

Every case renders each row through both paths — the frozen oracle in
``_reference_compose`` and the new ``BodyLayout``/``BodyRenderer`` — and
asserts identical text and styles per row plus identical section maps.
"""

from __future__ import annotations

import random
from collections.abc import Mapping

from rich.console import Console
from rich.rule import Rule
from rich.text import Text

from sase.pager._body_layout import build_body_layout
from sase.pager._body_lines import (
    build_span_index,
    logical_line_end,
    logical_line_starts,
    slice_styled_line,
)
from sase.pager._body_rows import BodyPaintState, BodyRenderer
from sase.pager._labels import PagerLabelLayer, build_label_layer
from sase.pager._line_mark import LineMark
from sase.pager.document import PagerDocument, PagerOrigin, PagerSection
from tests.pager._reference_compose import reference_compose_body

_CONSOLE = Console(color_system="truecolor")
_WIDTHS = (20, 37, 80, 118)


def _section(
    title: str,
    body: str | Text | object,
    *,
    identity: str | None = None,
    kind: str = "file",
) -> PagerSection:
    return PagerSection(
        identity=identity or f"file:/tmp/{title}",
        title=title,
        kind=kind,
        body=body,  # type: ignore[arg-type]
    )


def _span_key(text: Text) -> list[tuple[int, int, str]]:
    return [(span.start, span.end, str(span.style)) for span in text.spans]


def _assert_same_row(model_row: Text, oracle_row: Text) -> None:
    assert model_row.plain == oracle_row.plain
    assert _span_key(model_row) == _span_key(oracle_row)
    assert model_row.style == oracle_row.style


def _check_parity(
    document: PagerDocument,
    width: int,
    *,
    label_layer: PagerLabelLayer | None = None,
    pending_prefix: str = "",
    prepared_sections: Mapping[int, Text] | None = None,
    line_mark: LineMark | None = None,
    goto_accent: str | None = None,
    change_marks: Mapping[int, Mapping[int, str]] | None = None,
    removal_anchors: Mapping[int, set[int]] | None = None,
    rail_styles: Mapping[int, str] | None = None,
    history_styles: object | None = None,
    surface: str | None = None,
) -> None:
    oracle = reference_compose_body(
        document,
        width,
        label_layer=label_layer,
        pending_prefix=pending_prefix,
        prepared_sections=prepared_sections,
        line_mark=line_mark,
        goto_accent=goto_accent,
        change_marks=change_marks,
        removal_anchors=removal_anchors,
        rail_styles=rail_styles,
        history_styles=history_styles,
        surface=surface,
    )
    layout = build_body_layout(
        document,
        width,
        label_layer=label_layer,
        prepared_sections=prepared_sections,
        removal_anchors=removal_anchors,
    )
    assert layout.section_offsets == oracle.section_offsets
    assert layout.total_height == oracle.total_height
    assert layout.section_line_counts == oracle.section_line_counts
    assert layout.section_line_rows == oracle.section_line_rows
    assert len(oracle.rows) == oracle.total_height

    paint = BodyPaintState(
        label_layer=label_layer,
        pending_prefix=pending_prefix,
        prepared_sections=prepared_sections,
        line_mark=line_mark,
        goto_accent=goto_accent,
        change_marks=change_marks,
        rail_styles=rail_styles,
        history_styles=history_styles,
        surface=surface,
    )
    renderer = BodyRenderer(layout, paint)
    for row, oracle_row in enumerate(oracle.rows):
        _assert_same_row(renderer.render_row(row), oracle_row)
    assert renderer.rows_rendered == oracle.total_height


def _content_width(document: PagerDocument, width: int) -> int:
    from sase.pager._gutter import gutter_width, logical_line_count

    max_count = max(
        (logical_line_count(section.plain_text) for section in document.sections),
        default=0,
    )
    return max(width - gutter_width(max_count), 1)


def _wrap_corpus_document() -> PagerDocument:
    return PagerDocument(
        sections=(
            _section("plain", "alpha\nbeta gamma delta\n"),
            _section("long", "x" * 200 + "\nshort\n"),
            _section("tabs", "\tindented\ncol\tseparated\n"),
            _section("wide", "日本語の行🎉é\nplain after wide\n"),
            _section("spaces", "trailing   \n   leading\n"),
            _section("empty", ""),
            _section("newlines", "\n"),
            _section("blanks", "a\n\n\nb\n"),
        ),
        title="wrap corpus",
        origin=PagerOrigin.FILE,
    )


def test_parity_plain_and_wrapping() -> None:
    document = _wrap_corpus_document()
    for width in _WIDTHS:
        _check_parity(document, width)


def test_parity_multi_section_rules() -> None:
    document = PagerDocument(
        sections=tuple(
            _section(f"s{i}", f"body of section {i}\nsecond line\n", kind=kind)
            for i, kind in enumerate(["file", "bead", "agent", "patch"])
        ),
        title="4 sections",
        origin=PagerOrigin.FILE,
    )
    for width in _WIDTHS:
        _check_parity(document, width)


def _ansi_body() -> str:
    return (
        "\x1b[31mred line\x1b[0m plain tail\n"
        "middle \x1b[1;32mbold green\x1b[0m end\n"
        "\x1b[36mwide 日本語\x1b[0m\ttabbed\n"
    )


def test_parity_ansi_and_prepared_syntax() -> None:
    body = _ansi_body()
    document = PagerDocument(
        sections=(
            _section("ansi", body),
            _section("code", "def hello():\n    return '🐍'\n"),
        ),
        title="ansi",
        origin=PagerOrigin.FILE,
    )
    styled = document.sections[1].body_text
    styled.stylize("bold green", 0, 3)
    # A syntax span crossing the newline, like real highlight output.
    styled.stylize("italic yellow", 10, 20)
    prepared = {1: styled}
    for width in _WIDTHS:
        _check_parity(document, width, prepared_sections=prepared)


def _linked_document() -> PagerDocument:
    return PagerDocument(
        sections=(
            _section("links", "see src/sase/pager/app.py and https://example.test/x\n"),
            _section(
                "more",
                "bead sase-1es plus docs/guide.md here\nsecond line here\n",
            ),
        ),
        title="links",
        origin=PagerOrigin.FILE,
    )


def test_parity_document_labels_with_prefix_and_dangling() -> None:
    from sase.pager.document import section_target_spans

    document = _linked_document()
    assert (
        sum(
            len(section_target_spans(section, document.origin))
            for section in document.sections
        )
        > 0
    )
    for width in _WIDTHS:
        layer = build_label_layer(document, width=_content_width(document, width))
        _check_parity(document, width, label_layer=layer)
        first_hint = layer.labels[0].hint[:1]
        _check_parity(document, width, label_layer=layer, pending_prefix=first_hint)
        dangling = build_label_layer(
            document,
            width=_content_width(document, width),
            is_dangling=lambda _index, _target: True,
        )
        _check_parity(
            document,
            width,
            label_layer=dangling,
            pending_prefix=first_hint,
            surface="#1e1e2e",
        )


def test_parity_window_mode_labels() -> None:
    from sase.pager._labels import (
        PAGER_LABEL_TWO_KEY_CAPACITY,
        LabelWindowScope,
    )

    lines = [
        f"visit src/module{i:04d}.py for details here\n"
        for i in range(PAGER_LABEL_TWO_KEY_CAPACITY + 100)
    ]
    document = PagerDocument(
        sections=(_section("dense", "".join(lines)),),
        title="dense",
        origin=PagerOrigin.FILE,
    )
    width = 80
    layer = build_label_layer(
        document,
        width=_content_width(document, width),
        window_scope=LabelWindowScope(0, 1_000_000),
        section_offsets=(0,),
    )
    assert layer.mode == "window"
    assert layer.labels
    _check_parity(document, width, label_layer=layer)


def test_parity_goto_marks_anchors_and_rails() -> None:
    from sase.pager.history.styles import default_history_styles

    styles = default_history_styles()
    document = PagerDocument(
        sections=(
            _section("a", "one\n" + "y" * 100 + "\nthree\nfour\n"),
            _section("b", "alpha\nbeta\n"),
        ),
        title="marks",
        origin=PagerOrigin.FILE,
    )
    change_marks = {0: {1: "added", 3: "changed"}, 1: {2: "added"}}
    removal_anchors = {0: {0, 2}, 1: {1}}
    rail_styles = {0: styles.rail_past}
    for width in _WIDTHS:
        _check_parity(
            document,
            width,
            line_mark=LineMark(0, 2, 3),
            goto_accent="#FFAF5F",
            change_marks=change_marks,
            removal_anchors=removal_anchors,
            rail_styles=rail_styles,
            history_styles=styles,
        )


def test_parity_non_text_renderable() -> None:
    document = PagerDocument(
        sections=(
            _section("plain", "alpha\n"),
            _section("rule", Rule("see src/sase/pager/app.py here")),
        ),
        title="mixed",
        origin=PagerOrigin.FILE,
    )
    for width in (20, 80):
        layer = build_label_layer(document, width=_content_width(document, width))
        _check_parity(document, width, label_layer=layer)


def test_parity_resolved_styles_under_truecolor() -> None:
    """Spot-check resolved styles, not just span records, on a rich row."""
    from sase.pager.history.styles import default_history_styles

    styles = default_history_styles()
    document = _linked_document()
    width = 37
    layer = build_label_layer(document, width=_content_width(document, width))
    oracle = reference_compose_body(
        document,
        width,
        label_layer=layer,
        line_mark=LineMark(0, 1, 1),
        goto_accent="#FFAF5F",
        history_styles=styles,
    )
    layout = build_body_layout(document, width, label_layer=layer)
    paint = BodyPaintState(
        label_layer=layer,
        line_mark=LineMark(0, 1, 1),
        goto_accent="#FFAF5F",
        history_styles=styles,
    )
    renderer = BodyRenderer(layout, paint)
    for row, oracle_row in enumerate(oracle.rows):
        model_row = renderer.render_row(row)
        for offset in (0, len(model_row.plain) // 2, len(model_row.plain) - 1):
            assert model_row.get_style_at_offset(
                _CONSOLE, offset
            ) == oracle_row.get_style_at_offset(_CONSOLE, offset)


def _random_line(rng: random.Random, index: int) -> str:
    pool = [
        f"plain words number {index}",
        f"see src/module{index % 50}.py here",
        "https://example.test/docs/page",
        f"bead sase-{100 + (index % 7)}",
        "\ttabbed\tindent",
        "日本語の行🎉é combining",
        "x" * (30 + index % 160),
        "trailing spaces   ",
        "",
        "   ",
    ]
    return rng.choice(pool)


def test_parity_randomized_documents() -> None:
    from sase.pager.history.styles import default_history_styles

    styles = default_history_styles()
    rng = random.Random(20261002)
    for trial in range(24):
        sections = tuple(
            _section(
                f"r{trial}s{i}",
                "\n".join(
                    _random_line(rng, trial * 100 + j)
                    for j in range(rng.randint(1, 15))
                ),
                kind=rng.choice(["file", "bead", "agent"]),
            )
            for i in range(rng.randint(1, 3))
        )
        document = PagerDocument(
            sections=sections, title=f"random {trial}", origin=PagerOrigin.FILE
        )
        width = rng.choice(list(_WIDTHS))
        layer = build_label_layer(document, width=_content_width(document, width))
        pending = ""
        if layer.labels and rng.random() < 0.5:
            pending = rng.choice(layer.labels).hint[:1]
        dangling = rng.random() < 0.3
        check_layer = layer
        if dangling:
            check_layer = build_label_layer(
                document,
                width=_content_width(document, width),
                is_dangling=lambda _i, target: hash(target.text) % 2 == 0,
            )
        marks = (
            {0: {1: "added"}} if rng.random() < 0.3 and sections[0].plain_text else None
        )
        anchors = {0: {0}} if rng.random() < 0.3 else None
        accent = "#FFAF5F" if rng.random() < 0.3 else None
        mark = (
            LineMark(0, 1, 2) if accent is not None and sections[0].plain_text else None
        )
        _check_parity(
            document,
            width,
            label_layer=check_layer,
            pending_prefix=pending,
            line_mark=mark,
            goto_accent=accent,
            change_marks=marks,
            removal_anchors=anchors,
            history_styles=styles if marks or anchors else None,
        )


def test_slice_matches_text_split() -> None:
    """Styled extraction equals Text.split on fixed random inputs."""
    rng = random.Random(424242)
    styles = ["bold red", "italic", "bold green", "dim", "underline blue"]
    for _trial in range(60):
        lines = [
            "".join(rng.choice("ab 日本語🎉\tx") for _ in range(rng.randint(0, 25)))
            for _ in range(rng.randint(1, 8))
        ]
        text = Text("\n".join(lines))
        for _span in range(rng.randint(0, 6)):
            size = len(text.plain)
            if size:
                start = rng.randint(0, size - 1)
                text.stylize(rng.choice(styles), start, rng.randint(start + 1, size))
        expected = text.split("\n") if text.plain else ()
        if text.plain:
            starts = logical_line_starts(text.plain)
            assert len(starts) == len(expected)
            index = build_span_index(text)
            for line_pos, want in enumerate(expected):
                got = slice_styled_line(
                    text,
                    starts[line_pos],
                    logical_line_end(starts, line_pos, text.plain),
                    index=index,
                )
                _assert_same_row(got, want)
        else:
            assert logical_line_starts("") == ()
            assert len(expected) == 1


def test_layout_scales_to_100k_short_lines() -> None:
    import time

    body = "".join(f"line {i:06d} with some short text\n" for i in range(100_000))
    document = PagerDocument(
        sections=(_section("big", body),), title="big", origin=PagerOrigin.FILE
    )
    started = time.perf_counter()
    layout = build_body_layout(document, 80)
    elapsed = time.perf_counter() - started
    assert layout.lines_laid_out == 100_000
    assert layout.total_height == 100_000
    assert layout.section_line_counts == (100_000,)
    # Generous regression bound for shared hosts; the measured number goes
    # in the bead note (about 0.1 s on athena).
    assert elapsed < 5.0


def test_single_row_costs_one_line_on_100k_lines() -> None:
    body = "".join(f"line {i:06d} with some short text\n" for i in range(100_000))
    document = PagerDocument(
        sections=(_section("big", body),), title="big", origin=PagerOrigin.FILE
    )
    layout = build_body_layout(document, 80)
    renderer = BodyRenderer(layout, BodyPaintState())
    row = renderer.render_row(50_000)
    assert row.plain == " 50001│ line 050000 with some short text"
    assert renderer.lines_materialized == 1
    assert renderer.rows_rendered == 1


def test_relabel_recomputes_only_changed_lines() -> None:
    document = PagerDocument(
        sections=(
            _section(
                "links",
                "see src/a.py here\nplain middle\nsee src/b.py here\ntail\n",
            ),
        ),
        title="relabel",
        origin=PagerOrigin.FILE,
    )
    width = 80
    full = build_label_layer(document, width=_content_width(document, width))
    assert len(full.labels) >= 2
    layout = build_body_layout(document, width, label_layer=full)
    empty = PagerLabelLayer(
        labels=(),
        hint_to_label_index={},
        labels_by_section=tuple(() for _ in document.sections),
        target_count=full.target_count,
        mode="document",
    )
    relabeled = layout.relabel(empty)
    changed_lines = sum(
        1
        for line_pos in range(len(layout.section_states[0].starts))
        if layout.section_states[0].fingerprints[line_pos]
        != relabeled.section_states[0].fingerprints[line_pos]
    )
    assert 0 < changed_lines <= 2
    assert relabeled.lines_laid_out == changed_lines
    oracle = reference_compose_body(document, width, label_layer=empty)
    assert relabeled.section_offsets == oracle.section_offsets
    assert relabeled.total_height == oracle.total_height
    assert relabeled.section_line_rows == oracle.section_line_rows
    paint = BodyPaintState(label_layer=empty)
    renderer = BodyRenderer(relabeled, paint)
    for row, oracle_row in enumerate(oracle.rows):
        _assert_same_row(renderer.render_row(row), oracle_row)

    identical = layout.relabel(full)
    assert identical.lines_laid_out == 0
    assert identical.section_states[0] is layout.section_states[0]
    assert identical.total_height == layout.total_height


def test_relabel_rejects_a_foreign_layer() -> None:
    import pytest

    document = PagerDocument(
        sections=(_section("a", "alpha\n"), _section("b", "beta\n")),
        title="two",
        origin=PagerOrigin.FILE,
    )
    layout = build_body_layout(document, 40)
    other = PagerDocument(
        sections=(_section("a", "alpha\n"),), title="one", origin=PagerOrigin.FILE
    )
    foreign = build_label_layer(other, width=40)
    with pytest.raises(ValueError):
        layout.relabel(foreign)


def test_render_row_never_raises() -> None:
    document = PagerDocument(
        sections=(_section("a", "alpha\n"),), title="a", origin=PagerOrigin.FILE
    )
    layout = build_body_layout(document, 40)
    renderer = BodyRenderer(layout, BodyPaintState())
    # Out-of-range rows clamp like the reading anchor instead of raising.
    assert renderer.render_row(-5) == renderer.render_row(0)
    assert renderer.render_row(100_000) == renderer.render_row(layout.total_height - 1)

    empty_doc = PagerDocument(sections=(), title="empty", origin=PagerOrigin.FILE)
    empty_layout = build_body_layout(empty_doc, 40)
    assert empty_layout.total_height == 0
    assert BodyRenderer(empty_layout, BodyPaintState()).render_row(0) == Text("")


def test_mismatched_prepared_falls_back_to_body() -> None:
    document = PagerDocument(
        sections=(_section("a", "hello\nworld\n"),),
        title="a",
        origin=PagerOrigin.FILE,
    )
    corrupt = Text("completely different text here\n")
    layout = build_body_layout(document, 40, prepared_sections={0: corrupt})
    plain_layout = build_body_layout(document, 40)
    assert layout.section_line_rows == plain_layout.section_line_rows
    renderer = BodyRenderer(layout, BodyPaintState(prepared_sections={0: corrupt}))
    plain_renderer = BodyRenderer(plain_layout, BodyPaintState())
    for row in range(layout.total_height):
        _assert_same_row(renderer.render_row(row), plain_renderer.render_row(row))
