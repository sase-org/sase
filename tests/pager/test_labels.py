"""Tests for pager link-label assignment and pure rendering."""

from __future__ import annotations

from sase.pager._labels import (
    LabelWindowScope,
    PAGER_LABEL_TWO_KEY_CAPACITY,
    build_label_layer,
    render_section_with_labels,
)
from sase.pager.document import AttachedTarget, PagerDocument, PagerOrigin, PagerSection


def _url_lines(count: int) -> str:
    return "\n".join(f"https://example.test/{index}" for index in range(count)) + "\n"


def _document(body: str, *, origin: PagerOrigin = PagerOrigin.FILE) -> PagerDocument:
    section = PagerSection(
        identity="file:/tmp/links.txt",
        title="links.txt",
        kind="file",
        body=body,
    )
    return PagerDocument(sections=(section,), title="links", origin=origin)


def _attached_document(count: int) -> PagerDocument:
    pieces = [f"x{index}" for index in range(count)]
    body = " ".join(pieces)
    targets: list[AttachedTarget] = []
    cursor = 0
    for index, piece in enumerate(pieces):
        start = cursor
        end = start + len(piece)
        targets.append(
            AttachedTarget(
                kind="file",
                target=f"file:/tmp/{index}.txt",
                start=start,
                end=end,
            )
        )
        cursor = end + 1
    section = PagerSection(
        identity="file:/tmp/attached.txt",
        title="attached.txt",
        kind="file",
        body=body,
        targets=tuple(targets),
    )
    return PagerDocument(sections=(section,), title="attached", origin=PagerOrigin.FILE)


def test_label_layer_assigns_document_order_hints_to_scanned_links() -> None:
    document = _document("open src/sase/pager/app.py and https://example.test/page\n")

    layer = build_label_layer(document, width=80)

    assert layer.mode == "document"
    assert layer.target_count == 2
    assert layer.hint_to_label_index == {"0": 0, "1": 1}


def test_render_section_with_labels_paints_capsules_and_kind_glyphs() -> None:
    document = _document("open src/sase/pager/app.py and https://example.test/page\n")
    section = document.sections[0]
    layer = build_label_layer(document, width=80)

    rendered = render_section_with_labels(
        section,
        layer.labels_by_section[0],
    )

    assert "[0]▤\u00a0src/sase/pager/app.py" in rendered.plain
    assert "[1]↗\u00a0https://example.test/page" in rendered.plain


def test_zero_link_section_renders_without_capsules() -> None:
    document = _document("plain prose with no target spans\n")
    section = document.sections[0]
    layer = build_label_layer(document, width=80)

    rendered = render_section_with_labels(section, layer.labels_by_section[0])

    assert layer.target_count == 0
    assert rendered.plain == section.body_text.plain
    assert "[" not in rendered.plain


def test_label_assignment_is_stable_across_reflow_widths() -> None:
    document = _document(_url_lines(60))

    narrow = build_label_layer(document, width=40)
    wide = build_label_layer(document, width=120)

    assert [label.hint for label in narrow.labels] == [
        label.hint for label in wide.labels
    ]
    assert narrow.labels[-1].hint == wide.labels[-1].hint


def test_window_scoped_fallback_is_dormant_until_two_key_capacity() -> None:
    document = _attached_document(PAGER_LABEL_TWO_KEY_CAPACITY + 1)

    layer = build_label_layer(
        document,
        width=80,
        window_scope=LabelWindowScope(0, 20),
        section_offsets=(0,),
    )

    assert layer.mode == "window"
    assert layer.target_count == PAGER_LABEL_TWO_KEY_CAPACITY + 1
    assert 0 < layer.visible_label_count <= PAGER_LABEL_TWO_KEY_CAPACITY
