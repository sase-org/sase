"""Container re-key must not leave an empty `@default` strip behind.

A launching clan's synthetic container first renders with no generation and
no clan tribe (`@default`), then re-projects with a generation and
`clan_tribe="research"`. The sticky layer retires `@default` in that same
sync because its backing member is now under `@research`.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions.agents._display_helpers import panel_widget_id_for_key
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets import AgentList
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
)


def _member(suffix: str, generation: str | None, clan_tribe: str | None) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="cl",
        project_file="/tmp/projects/demo/demo.sase",
        status="DONE",
        start_time=datetime(2026, 7, 19, 8, 0, 0),
        stop_time=datetime(2026, 7, 19, 8, 30, 0),
        raw_suffix=suffix,
        agent_name="m1",
        tribe=None,
        agent_clan="alpha",
        agent_clan_generation=generation,
        clan_tribe=clan_tribe,
    )


async def test_container_rekey_retires_default_panel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-projecting a clan container unmounts the emptied `@default` strip."""
    patch_startup_loaders(
        monkeypatch,
        agents=[_member("s1", None, None), _member("s2", None, None)],
    )

    async with AcePage(
        query='"demo"',
        patches=patches(),
        initial_tab="agents",
    ) as page:
        await wait_for_startup(page)
        await page.wait_for(lambda _screen: page.app._panel_group.panel_keys == [None])

        new_proj = project_clan_tree(
            [_member("s1", "g1", "research"), _member("s2", "g1", "research")]
        )
        new_container = next(a for a in new_proj if a.is_clan_container)
        previous = list(page.app._agents)
        page.app._agents_with_children = new_proj
        page.app._agents = [new_container]
        page.app._refresh_agents_display_after_finalize(
            previous_agents=previous,
            defer_detail=True,
        )

        await page.wait_for(
            lambda _screen: page.app._panel_group.panel_keys == ["research"]
        )
        assert page.app._session_mounted_panel_key_set() == {"research"}
        default_widget_id = panel_widget_id_for_key(None)
        research_widget_id = panel_widget_id_for_key("research")
        await page.wait_for(
            lambda _screen: (
                research_widget_id
                in {widget.id for widget in page.app.query(AgentList)}
            )
        )
        await page.wait_for(
            lambda _screen: (
                default_widget_id
                not in {widget.id for widget in page.app.query(AgentList)}
            )
        )
