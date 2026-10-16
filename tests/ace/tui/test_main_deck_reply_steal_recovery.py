"""Main-deck Reply selection survives a background scroll reset.

A same-subject Main re-delivery can clamp the spread scroll offset back to
the top while no navigation is in flight. The scroll watcher then derives the
top card and overwrites the stored selection even though the view still shows
the selected card. The shared visual readiness helper must re-drive the
selection instead of timing out on a state that will never arrive (Full CI
``visual-test`` readiness timeouts in
``test_renamed_generic_agent_session_root_png_snapshot`` and
``test_agents_session_lane_neighbors_png_snapshot``).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets import AgentDetail
from tests.ace.tui.visual._ace_agents_png_snapshot_agent_session_fixtures import (
    renamed_generic_agent_session_agents,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    main_deck_scroll,
    pin_agents_visual_now,
    select_main_card,
    select_navigable_main_card,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)


async def test_reply_selection_recovers_after_background_scroll_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The readiness helper re-drives Reply after a scroll-clamp steal."""
    pin_agents_visual_now(monkeypatch, datetime(2026, 7, 18, 11, 10, 0))
    patch_startup_loaders(monkeypatch, agents=renamed_generic_agent_session_agents())

    async with AcePage(query='"visual-family"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("shift+tab")
        await page.expect_state("tab", "agents")
        await page.expect_state("agent_count", 1)
        await page.press("l")
        await page.expect_state("agent_count", 3)
        await wait_for_visual_idle(page)
        await select_main_card(page, "reply")
        await wait_for_visual_idle(page)

        detail = page.app.query_one("#agent-detail-panel", AgentDetail)
        panel = detail.deck_area.panel(0)
        scroll = main_deck_scroll(page)
        assert panel.main_view._spread_pending_card is None
        assert scroll.max_scroll_y > 0

        # Simulate the re-delivery clamp through the real scroll watcher:
        # move away from the top and back with no navigation in flight, so
        # the watcher derives Context and overwrites the stored selection
        # while the view still shows Reply.
        scroll.scroll_y = scroll.max_scroll_y
        await page.pause(0)
        scroll.scroll_y = 0
        await wait_for_visual_idle(page)
        assert panel.main_view._spread_pending_card is None
        assert panel.main_view.active_card_id == "reply"
        assert panel._main_active_card == "context"

        # Must re-drive Reply instead of timing out waiting for it.
        await select_navigable_main_card(page, "reply")
        assert detail.deck_area.panel(0)._main_active_card == "reply"
