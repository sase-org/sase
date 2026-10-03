"""Widget tests for the virtual ``PagerBodyScroll`` body.

Row text and style come from the line model through ``view.row_text``;
``render_line`` only converts those rows to strips. Parity against the
frozen oracle proves the model rows, while the counters prove the widget
paints only visible rows through its bounded strip cache.
"""

from __future__ import annotations

import pytest

from rich.text import Text

from sase.ace.testing.wait import wait_for
from sase.pager._body_rows import BodyRenderer
from sase.pager.app import SasePager
from sase.pager.document import (
    PagerDocument,
    PagerOrigin,
    PagerSection,
    RawSourceSpec,
)
from tests.pager._app_helpers import (
    body_scroll,
    pager_screen,
)
from tests.pager._reference_compose import ReferenceBody, reference_compose_body


def _section(title: str, body: str) -> PagerSection:
    return PagerSection(
        identity=f"file:/tmp/{title}", title=title, kind="file", body=body
    )


def _plain_document(count: int = 200) -> PagerDocument:
    body = "".join(
        f"line {index:04d} with some trailing words\n" for index in range(count)
    )
    return PagerDocument(
        sections=(_section("plain", body),), title="plain", origin=PagerOrigin.FILE
    )


def _link_document() -> PagerDocument:
    body = "see src/sase/pager/app.py and https://example.test/x here\nsecond line\n"
    return PagerDocument(
        sections=(_section("links", body),), title="links", origin=PagerOrigin.FILE
    )


def _python_document() -> PagerDocument:
    return PagerDocument(
        sections=(
            PagerSection(
                identity="file:/tmp/demo.py",
                title="demo.py",
                kind="file",
                body="def hello():\n    return 42\n",
                raw_source=RawSourceSpec(language="python", eligible=True),
            ),
        ),
        title="demo.py",
        origin=PagerOrigin.FILE,
    )


def _assert_same_row(model_row: Text, oracle_row: Text) -> None:
    assert model_row.plain == oracle_row.plain
    assert [(span.start, span.end, str(span.style)) for span in model_row.spans] == [
        (span.start, span.end, str(span.style)) for span in oracle_row.spans
    ]
    assert model_row.style == oracle_row.style


def _oracle_for_view(view: object, width: int, **overrides: object) -> ReferenceBody:
    pending = getattr(view, "_label_pending_prefix", "")
    prepared = view._prepared_section_texts()  # type: ignore[attr-defined]
    params: dict[str, object] = {
        "label_layer": getattr(view, "_label_layer", None),
        "pending_prefix": pending,
        "prepared_sections": prepared,
    }
    params.update(overrides)
    return reference_compose_body(view.document, width, **params)  # type: ignore[arg-type]


async def _assert_visible_parity(pilot: object, app: SasePager) -> None:
    screen = pager_screen(app)
    view = screen.focused_view
    scroll = body_scroll(app)
    width = view._body_paint_width()
    assert screen._body is not None
    oracle = _oracle_for_view(view, width)
    total = screen._body.total_height
    assert len(oracle.rows) == total
    viewport = max(int(scroll.size.height), 1)
    positions = (0, total // 2, max(total - viewport, 0))
    for scroll_y in positions:
        scroll.scroll_to(y=scroll_y, animate=False, immediate=True)
        await pilot.pause()  # type: ignore[attr-defined]
        top = int(scroll.scroll_y)
        for offset in range(viewport):
            row = top + offset
            if row >= total:
                break
            _assert_same_row(view.row_text(row), oracle.rows[row])


async def test_widget_rows_match_oracle_at_several_scroll_positions() -> None:
    app = SasePager(_plain_document())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await _assert_visible_parity(pilot, app)


async def test_widget_rows_match_oracle_after_resize() -> None:
    app = SasePager(_plain_document())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        screen = pager_screen(app)
        view = screen.focused_view
        scroll = body_scroll(app)
        first_width = view._body_paint_width()
        oracle = _oracle_for_view(view, first_width)
        assert view.row_text(0).plain == oracle.rows[0].plain

        await pilot.resize_terminal(100, 30)
        await pilot.pause()
        await _assert_visible_parity(pilot, app)

        # The one-cell side pads are baked into the strips (not widget
        # padding), so the scrollable region starts at the pane edge while
        # each painted strip spans it exactly.
        assert scroll.scrollable_content_region.x - scroll.region.x == 0
        strip = scroll.render_line(0)
        assert strip.cell_length == scroll.scrollable_content_region.width


async def test_widget_rows_match_oracle_after_a_label_prefix() -> None:
    app = SasePager(_link_document())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        screen = pager_screen(app)
        view = screen.focused_view
        scroll = body_scroll(app)
        assert view._label_layer is not None and view._label_layer.labels
        laid_out = view._body.lines_laid_out if view._body is not None else 0

        view._label_pending_prefix = view._label_layer.labels[0].hint[:1]
        view._repaint_label_state()
        await pilot.pause()

        assert view._body is not None
        assert view._body.lines_laid_out == laid_out
        assert view._body_renderer is not None
        viewport = max(int(scroll.size.height), 1)
        assert view._body_renderer.rows_rendered <= viewport
        await _assert_visible_parity(pilot, app)


async def test_syntax_publish_matches_oracle_without_relayout() -> None:
    app = SasePager(_python_document())
    async with app.run_test(size=(80, 24)) as pilot:
        screen = pager_screen(app)
        view = screen.focused_view
        await pilot.pause()
        await wait_for(
            pilot,
            lambda: ("file:/tmp/demo.py", None) in view._syntax_prepared,
        )
        await pilot.pause()

        assert view._body is not None
        layout_before = view._body
        laid_out = layout_before.lines_laid_out
        view._publish_syntax_update()
        await pilot.pause()

        assert view._body is layout_before
        assert view._body.lines_laid_out == laid_out
        await _assert_visible_parity(pilot, app)


async def test_opening_a_50k_line_document_paints_at_most_two_viewports() -> None:
    body = "".join(
        f"line {index:06d} with some short text\n" for index in range(50_000)
    )
    document = PagerDocument(
        sections=(_section("big", body),), title="big", origin=PagerOrigin.FILE
    )
    app = SasePager(document)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        screen = pager_screen(app)
        view = screen.focused_view
        scroll = body_scroll(app)
        assert view._body_renderer is not None
        viewport = max(int(scroll.size.height), 1)
        assert viewport > 0
        assert view._body_renderer.rows_rendered <= 2 * viewport

        before = view._body_renderer.rows_rendered
        await pilot.press("j")
        await pilot.pause()
        assert int(scroll.scroll_y) == 1
        assert view._body_renderer.rows_rendered - before == 1


async def test_render_row_failure_paints_the_plain_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = SasePager(_plain_document(20))
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        scroll = body_scroll(app)

        def _raise(row: int) -> Text:
            raise RuntimeError("boom")

        monkeypatch.setattr(BodyRenderer, "render_row", _raise)
        strip = scroll.render_line(0)

        assert "line 0000" in strip.text
