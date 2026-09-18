"""Shared helpers for Agents-tab PNG visual snapshot tests."""

from __future__ import annotations

from datetime import datetime
from xml.etree import ElementTree

import pytest

from sase.ace.testing import AcePage


async def choose_agent_metadata_view(page: AcePage) -> None:
    """Choose the metadata-only Agents detail view through the current picker."""
    await page.press("p")
    await page.expect_modal("AgentViewModal")
    await page.press("[")
    await page.expect_no_modal()


def pin_agents_visual_now(monkeypatch: pytest.MonkeyPatch, now: datetime) -> None:
    """Pin Agents-tab runtime formatting for date-sensitive snapshots."""
    from sase.ace.tui.actions.agents import (
        _display_panel_patches,
        _loading_compute_finalize,
        _loading_finalize,
    )
    from sase.ace.tui.models import _agent_time_wait
    from sase.ace.tui.models import agent as agent_module
    from sase.ace.tui.models import agent_time
    from sase.ace.tui.widgets.prompt_panel import _agent_queue_section
    from sase.core import time as core_time

    for module in (
        core_time,
        agent_module,
        agent_time,
        _agent_time_wait,
        _agent_queue_section,
        _display_panel_patches,
        _loading_compute_finalize,
        _loading_finalize,
    ):
        monkeypatch.setattr(module, "local_now", lambda: now)


def assert_page_svg_contains(page: AcePage, text: str) -> None:
    svg = page.export_svg(title="ACE visual assertion")
    svg_plain = _page_svg_text(svg)
    assert text in svg_plain


def _page_svg_text(svg: str) -> str:
    """Return decoded text content from the exported SVG."""
    root = ElementTree.fromstring(svg)
    text_nodes = (
        "".join(element.itertext())
        for element in root.iter()
        if element.tag.rsplit("}", 1)[-1] == "text"
    )
    return "\n".join(text_nodes).replace("\xa0", " ")


def _page_svg_compact_styled_text(page: AcePage) -> str:
    """Return the page's SVG text content with styling boundaries collapsed.

    Rich represents spaces between differently styled SVG runs as
    x-offsets, not text nodes, so the caller compares against a compacted
    token stream with all spaces removed.
    """
    svg = page.export_svg(title="ACE visual assertion")
    return _page_svg_text(svg).replace(" ", "").replace("\n", "")


def assert_page_svg_styled_text_contains(page: AcePage, text: str) -> None:
    """Assert text across adjacent SVG elements with different Rich styles."""
    compact_text = text.replace(" ", "")
    svg_plain = _page_svg_compact_styled_text(page)
    assert compact_text in svg_plain, f"styled SVG text did not contain {text!r}"


def assert_page_svg_styled_text_absent(page: AcePage, text: str) -> None:
    """Assert text is absent across adjacent SVG elements with different styles."""
    compact_text = text.replace(" ", "")
    svg_plain = _page_svg_compact_styled_text(page)
    assert compact_text not in svg_plain, (
        f"styled SVG text unexpectedly contained {text!r}"
    )
