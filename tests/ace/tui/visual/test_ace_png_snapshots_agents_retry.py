"""ACE TUI PNG visual coverage for retry and fallback agent states."""

from __future__ import annotations

from datetime import datetime
import time

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.models.agent import AttemptRecord
from sase.ace.tui.models.agent_loader import _apply_status_overrides
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    retry_agent,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_VISUAL_NOW = datetime(2026, 7, 6, 12, 0, 0)


async def _open_agents_tab(page: AcePage, *, agent_count: int) -> None:
    await wait_for_startup(page)
    await page.press("shift+tab")
    await page.expect_state("tab", "agents")
    await page.expect_state("agent_count", agent_count)
    await wait_for_visual_idle(page)


async def test_retry_countdown_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now_epoch = _VISUAL_NOW.timestamp()
    monkeypatch.setattr(time, "time", lambda: now_epoch)
    rows = [
        retry_agent(
            name="countdown",
            status="RETRYING",
            start_time=datetime(2026, 7, 6, 11, 58, 0),
            raw_suffix="20260706115800",
            retry_status="retrying",
            retry_count=1,
            max_retries=3,
            retry_next_at_epoch=now_epoch + 9,
        )
    ]
    patch_startup_loaders(monkeypatch, agents=rows)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await _open_agents_tab(page, agent_count=1)

        await wait_for_svg_contains(page, "RETRYING (9s)")
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "RETRYING (9s)")
        assert_page_svg_contains(page, "Retries:")
        assert_page_svg_contains(page, "1/3")
        ace_png_visual.assert_page_png(
            page,
            "agents_retry_countdown_120x40",
            title="ACE agents retry countdown",
        )


async def test_running_fallback_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        retry_agent(
            name="fallback",
            status="RUNNING",
            start_time=datetime(2026, 7, 6, 11, 59, 0),
            raw_suffix="20260706115900",
            retry_status="running_fallback",
            retry_count=2,
            max_retries=2,
            using_fallback=True,
            fallback_model="claude-sonnet-4-5",
        )
    ]
    patch_startup_loaders(monkeypatch, agents=rows)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await _open_agents_tab(page, agent_count=1)

        await wait_for_svg_contains(page, "claude-sonnet-4-5")
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "RUNNING")
        assert_page_svg_contains(page, "↻2▸sonnet")
        assert_page_svg_contains(page, "Fallback:")
        assert_page_svg_contains(page, "claude-sonnet-4-5")
        ace_png_visual.assert_page_png(
            page,
            "agents_retry_running_fallback_120x40",
            title="ACE agents running fallback",
        )


async def test_completed_retry_chain_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_suffix = "20260706114500"
    retry_one_suffix = "20260706115000"
    retry_two_suffix = "20260706115500"
    rows = [
        retry_agent(
            name="chain",
            status="FAILED (RETRIED)",
            start_time=datetime(2026, 7, 6, 11, 45, 0),
            stop_time=datetime(2026, 7, 6, 11, 46, 0),
            raw_suffix=root_suffix,
            retry_chain_root_timestamp=root_suffix,
            retried_as_timestamp=retry_one_suffix,
            retry_terminal=True,
        ),
        retry_agent(
            name="chain",
            status="FAILED (RETRIED)",
            start_time=datetime(2026, 7, 6, 11, 50, 0),
            stop_time=datetime(2026, 7, 6, 11, 51, 0),
            raw_suffix=retry_one_suffix,
            retry_attempt=1,
            retry_of_timestamp=root_suffix,
            retry_chain_root_timestamp=root_suffix,
            retried_as_timestamp=retry_two_suffix,
            retry_terminal=True,
        ),
        retry_agent(
            name="chain",
            status="DONE",
            start_time=datetime(2026, 7, 6, 11, 55, 0),
            stop_time=datetime(2026, 7, 6, 11, 57, 0),
            raw_suffix=retry_two_suffix,
            retry_attempt=2,
            retry_of_timestamp=retry_one_suffix,
            retry_chain_root_timestamp=root_suffix,
        ),
    ]
    _apply_status_overrides(rows, classify_diff_badges=False)
    patch_startup_loaders(monkeypatch, agents=rows)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await _open_agents_tab(page, agent_count=3)

        await wait_for_svg_contains(page, "(RETRIED)")
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "(RETRIED)")
        assert_page_svg_contains(page, "↳")
        assert_page_svg_contains(page, "↻1")
        assert_page_svg_contains(page, "↻2")
        assert_page_svg_contains(page, "DONE")
        ace_png_visual.assert_page_png(
            page,
            "agents_retry_completed_chain_120x40",
            title="ACE agents completed retry chain",
        )


async def test_retries_exhausted_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        retry_agent(
            name="exhausted",
            status="FAILED",
            start_time=datetime(2026, 7, 6, 11, 50, 0),
            stop_time=datetime(2026, 7, 6, 11, 59, 0),
            raw_suffix="20260706115000",
            retry_count=3,
            max_retries=3,
            retry_terminal=True,
        )
    ]
    patch_startup_loaders(monkeypatch, agents=rows)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await _open_agents_tab(page, agent_count=1)

        await wait_for_svg_contains(page, "3/3")
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "FAILED")
        assert_page_svg_contains(page, "Retries:")
        assert_page_svg_contains(page, "3/3")
        ace_png_visual.assert_page_png(
            page,
            "agents_retry_exhausted_120x40",
            title="ACE agents retries exhausted",
        )


async def test_selected_retry_metadata_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    history = [
        AttemptRecord(
            attempt_number=1,
            status="failed",
            start_epoch=datetime(2026, 7, 6, 11, 54, 0).timestamp(),
            end_epoch=datetime(2026, 7, 6, 11, 55, 0).timestamp(),
            model="gpt-5",
            used_fallback=False,
            error_snippet="provider capacity exhausted",
            error_full="provider capacity exhausted",
            live_reply_path="/workspace/sase/artifacts/attempts/1/live_reply.md",
            timestamps_path=(
                "/workspace/sase/artifacts/attempts/1/live_reply_timestamps.jsonl"
            ),
        )
    ]
    rows = [
        retry_agent(
            name="metadata",
            status="RUNNING",
            start_time=datetime(2026, 7, 6, 11, 56, 0),
            raw_suffix="20260706115600",
            retry_status="running_retry",
            retry_count=1,
            max_retries=3,
            using_fallback=True,
            fallback_model="claude-sonnet-4-5",
            attempt_history=history,
        )
    ]
    patch_startup_loaders(monkeypatch, agents=rows)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await _open_agents_tab(page, agent_count=1)

        await wait_for_svg_contains(page, "Attempt 1")
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "Retries:")
        assert_page_svg_contains(page, "1/3")
        assert_page_svg_contains(page, "Attempt 1")
        assert_page_svg_contains(page, "failed:")
        assert_page_svg_contains(page, "Fallback:")
        ace_png_visual.assert_page_png(
            page,
            "agents_retry_selected_detail_120x40",
            title="ACE agents selected retry metadata",
        )
