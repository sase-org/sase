from __future__ import annotations

from sase.ace.tui.graphics import has_truecolor, image_render_context


def test_image_render_context_detects_truecolor() -> None:
    context = image_render_context({"COLORTERM": "truecolor", "TERM": "xterm-256color"})

    assert context.truecolor is True
    assert "truecolor" in context.reason


def test_has_truecolor_accepts_term_marker() -> None:
    assert has_truecolor({"TERM": "xterm-truecolor"}) is True
    assert has_truecolor({"TERM": "xterm-256color"}) is False
