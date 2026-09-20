"""Shared helpers for Agents-tab PNG visual snapshot tests."""

from __future__ import annotations

from datetime import datetime
from xml.etree import ElementTree

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets import AgentDetail
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    wait_for_state,
    wait_for_visual_idle,
)


async def choose_agent_metadata_view(page: AcePage) -> None:
    """Choose the metadata-only Agents detail view through the current picker.

    The picker opens on `p`. Metadata-only is the `[` layout choice; `0`/`n`
    are contained without selecting and leave the modal open.
    """
    await page.press("p")
    await page.expect_modal("AgentViewModal")
    await page.press("[")
    await page.expect_no_modal()
    # Choosing the layout that is already current changes nothing, so no
    # surface refresh follows. A countdown tick during the modal would leave
    # the header without its ``(p)`` hint until the next tick; refresh once
    # after the modal is gone so the frame does not depend on that race.
    page.app._update_agents_info_panel()
    await wait_for_visual_idle(page)


async def choose_agent_secondary_larger_layout(page: AcePage) -> None:
    """Choose the visible Secondary-larger layout through the current picker."""
    await page.press("p")
    await page.expect_modal("AgentViewModal")
    await page.pause()
    await page.press("2")
    await page.expect_no_modal()
    await wait_for_visual_idle(page)


async def reveal_agent_file_view(page: AcePage) -> None:
    """Wait for File content, then show File via the File-larger layout.

    Fresh Agents detail stays metadata-only (`view: none`) until a non-metadata
    layout is chosen. Linked/external diff goldens assert the file-panel banner,
    which is not in the metadata summary. Choosing File mode alone leaves the
    saved metadata-only layout in place, so this uses the same File-larger
    path as the other Agents PNG helpers.
    """
    await reveal_agent_file_larger_layout(page)


async def reveal_agent_file_larger_layout(page: AcePage) -> None:
    """Wait for File content, then choose File-larger through the picker."""
    detail = page.app.query_one("#agent-detail-panel", AgentDetail)
    await wait_for_state(
        page,
        lambda: bool(detail._has_file_content),
        description="file content available",
    )
    await choose_agent_secondary_larger_layout(page)


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
