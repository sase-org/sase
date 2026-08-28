"""Tests for pager link-label assignment and pure rendering."""

from __future__ import annotations

from rich.color import Color
from rich.console import Console
from rich.style import Style
from rich.text import Text

from sase.ace.tui._artifact_tab_model import ARTIFACTS_ACCENTS, EXTERNAL_ACCENT
from sase.pager._labels import (
    LabelWindowScope,
    PAGER_LABEL_ALPHABET,
    PAGER_LABEL_TWO_KEY_CAPACITY,
    PagerLabel,
    build_label_layer,
    render_section_with_labels,
)
from sase.pager.document import AttachedTarget, PagerDocument, PagerOrigin, PagerSection

_CONSOLE = Console(color_system="truecolor")
_LABEL_BACKGROUND = Color.parse("#FFD75F")
_LABEL_MATCH_BACKGROUND = Color.parse("#FFFFAF")
_FILE_ACCENT = Color.parse(ARTIFACTS_ACCENTS["files"])
_URL_ACCENT = Color.parse(EXTERNAL_ACCENT)


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


def _attached_single_document(
    body: str,
    *,
    kind: str = "file",
    target: str = "file:/tmp/missing.txt",
) -> PagerDocument:
    section = PagerSection(
        identity="file:/tmp/attached.txt",
        title="attached.txt",
        kind="file",
        body=body,
        targets=(AttachedTarget(kind=kind, target=target, start=0, end=len(body)),),
    )
    return PagerDocument(sections=(section,), title="attached", origin=PagerOrigin.FILE)


def _style_at(text: Text, offset: int) -> Style:
    return text.get_style_at_offset(_CONSOLE, offset)


def _assert_label_style_boundary(
    rendered: Text,
    label: PagerLabel,
    *,
    icon: str,
    icon_color: Color | None,
    hint_background: Color | None,
    hint_dim: bool = False,
    icon_dim: bool = False,
) -> None:
    prefix = f"[{label.hint}]{icon}\u00a0{label.target.text}"
    start = rendered.plain.index(prefix)
    hint_end = start + len(f"[{label.hint}]")
    icon_end = hint_end + len(icon)
    space_end = icon_end + 1

    for offset in range(start, hint_end):
        style = _style_at(rendered, offset)
        assert style.bgcolor == hint_background
        assert bool(style.dim) is hint_dim

    for offset in range(hint_end, space_end):
        style = _style_at(rendered, offset)
        assert style.bgcolor is None
        assert bool(style.dim) is icon_dim
        if icon_color is not None:
            assert style.bold is True
            assert style.color == icon_color

    target_style = _style_at(rendered, space_end)
    assert target_style.bgcolor is None


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
    _assert_label_style_boundary(
        rendered,
        layer.labels[0],
        icon="▤",
        icon_color=_FILE_ACCENT,
        hint_background=_LABEL_BACKGROUND,
    )
    _assert_label_style_boundary(
        rendered,
        layer.labels[1],
        icon="↗",
        icon_color=_URL_ACCENT,
        hint_background=_LABEL_BACKGROUND,
    )


def test_render_section_with_labels_limits_matching_capsule_to_hint() -> None:
    document = _attached_document(len(PAGER_LABEL_ALPHABET) + 1)
    section = document.sections[0]
    layer = build_label_layer(document, width=80)
    label = next(label for label in layer.labels if len(label.hint) == 2)

    rendered = render_section_with_labels(
        section,
        layer.labels_by_section[0],
        pending_prefix=label.hint[:1],
    )

    assert f"[{label.hint}]▤\u00a0{label.target.text}" in rendered.plain
    _assert_label_style_boundary(
        rendered,
        label,
        icon="▤",
        icon_color=_FILE_ACCENT,
        hint_background=_LABEL_MATCH_BACKGROUND,
    )


def test_render_section_with_labels_dims_pending_nonmatches_without_background() -> (
    None
):
    document = _document("open src/sase/pager/app.py and https://example.test/page\n")
    section = document.sections[0]
    layer = build_label_layer(document, width=80)

    rendered = render_section_with_labels(
        section,
        layer.labels_by_section[0],
        pending_prefix="0",
    )

    assert "[1]↗\u00a0https://example.test/page" in rendered.plain
    _assert_label_style_boundary(
        rendered,
        layer.labels[1],
        icon="↗",
        icon_color=_URL_ACCENT,
        hint_background=None,
        hint_dim=True,
        icon_dim=True,
    )


def test_render_section_with_labels_keeps_dangling_label_dim_without_background() -> (
    None
):
    document = _attached_single_document("missing")
    section = document.sections[0]
    layer = build_label_layer(
        document,
        width=80,
        dangling_refs={"missing"},
    )

    rendered = render_section_with_labels(section, layer.labels_by_section[0])

    assert "[0]⊘\u00a0missing (missing)" in rendered.plain
    _assert_label_style_boundary(
        rendered,
        layer.labels[0],
        icon="⊘",
        icon_color=None,
        hint_background=None,
        hint_dim=True,
        icon_dim=True,
    )


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
