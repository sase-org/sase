"""Regression coverage for ACE footer visibility in the real app layout."""

from __future__ import annotations

import html
import re

import pytest
from textual.widgets import Footer as TextualFooter

from sase.ace.testing import AcePage
from sase.ace.tui.widgets import KeybindingFooter
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)


def _svg_text(svg: str) -> str:
    text_nodes = re.findall(r"<text[^>]*>(.*?)</text>", svg, re.S)
    plain_nodes = [re.sub(r"<[^>]+>", "", node) for node in text_nodes]
    return html.unescape("\n".join(plain_nodes)).replace("\xa0", " ")


def _assert_export_contains(exported: str, *fragments: str) -> None:
    plain = _svg_text(exported)
    missing = [fragment for fragment in fragments if fragment not in plain]
    assert not missing, f"missing footer fragments {missing!r} in:\n{plain}"


@pytest.mark.asyncio
async def test_custom_footer_status_visible_in_normal_one_line_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        await wait_for_visual_idle(page)

        assert list(page.app.query(TextualFooter)) == []
        _assert_export_contains(
            page.export_svg(title="ACE footer normal"),
            "mail",
            "rebase",
            "sync",
            "STOPPED",
        )


@pytest.mark.asyncio
async def test_leader_footer_final_grid_row_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches(), size=(80, 30)) as page:
        await wait_for_startup(page)

        footer = page.app.query_one(KeybindingFooter)
        footer.update_leader_bindings(current_tab="patches")
        await wait_for_visual_idle(page)

        _assert_export_contains(
            page.export_svg(title="ACE footer leader"),
            "LEADER",
            "run cmd (PR)",
            "models panel",
            "update SASE + CLIs + hood cache",
            "STOPPED",
        )
