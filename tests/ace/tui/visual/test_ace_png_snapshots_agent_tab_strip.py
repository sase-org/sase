"""ACE PNG coverage for the Agents tab strip (sase-1bc.7, machine tabs sase-1bc.9).

Hidden (pixel-identical to today), standard, attention, narrow overflow,
all three empty causes, a 32-character name, the tab picker, machine mode
with named-vs-machine aliases, a stale host, and BY_MACHINE on a machine
tab versus a named tab.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui import agent_tabs_settings as settings_mod
from sase.ace.tui.agent_tabs_settings import AgentTabsViewConfig
from sase.ace.tui.models import agent_tab_descriptors as descriptors_mod
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.agent_tab_descriptors import AgentTabStyleInputs
from sase.core.agent_tab import AgentTabKey
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_SASE = AgentTabKey.named("sase")
_BLOG = AgentTabKey.named("blog")


def _agent(
    name: str,
    *,
    tab: str | None = None,
    status: str = "RUNNING",
    origin_alias: str | None = None,
    origin_id: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/workspace/sase/visual_project.sase",
        status=status,
        start_time=datetime(2026, 9, 28, 8, 0, 0),
        raw_suffix=f"202609280800{name}",
        agent_name=f"visual.{name}",
        agent_tab=tab,
        fleet_origin_alias=origin_alias,
        fleet_origin_installation_id=origin_id,
    )


def _install_tab_view(
    monkeypatch: pytest.MonkeyPatch,
    *,
    machine_mode: bool = False,
    machine_order: tuple[tuple[str, str], ...] = (),
) -> None:
    """Pin the tab view config and style inputs for one golden."""
    view = AgentTabsViewConfig(
        machine_mode=machine_mode,
        machine_order=machine_order,
        pinned_by_alias={alias: iid for iid, alias in machine_order},
        named_order={},
        token=(machine_mode, tuple(machine_order)),
    )
    styles = AgentTabStyleInputs(machine_mode=machine_mode)
    monkeypatch.setattr(settings_mod, "agent_tabs_view_config", lambda: view)
    monkeypatch.setattr(
        descriptors_mod,
        "resolve_agent_tab_style_inputs",
        lambda *, allow_disk=False: styles,
    )
    settings_mod._agent_tabs_view_config_for_token.cache_clear()  # noqa: SLF001


async def _open_agents(page: AcePage) -> None:
    await wait_for_startup(page)
    await page.press("shift+tab")
    await page.expect_state("tab", "agents")
    await wait_for_visual_idle(page)


async def test_agents_tab_strip_hidden_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[_agent("one"), _agent("two")])
    _install_tab_view(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _open_agents(page)
        await page.expect_state("agent_count", 2)
        ace_png_visual.assert_page_png(
            page,
            "agents_tab_strip_hidden_120x40",
            title="ACE agents tab strip hidden with one tab",
        )


async def test_agents_tab_strip_standard_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(
        monkeypatch,
        agents=[
            _agent("one"),
            _agent("two", tab="sase"),
            _agent("three", tab="sase"),
            _agent("four", tab="blog"),
        ],
    )
    _install_tab_view(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _open_agents(page)
        for token in ("sase", "blog", "▐", "▌", "┊"):
            assert_page_svg_contains(page, token)
        ace_png_visual.assert_page_png(
            page,
            "agents_tab_strip_standard_120x40",
            title="ACE agents tab strip with named tabs",
        )


async def test_agents_tab_strip_attention_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    done = _agent("done-one", tab="sase", status="DONE")
    patch_startup_loaders(
        monkeypatch,
        agents=[
            _agent("one"),
            _agent("asking", tab="sase", status="QUESTION"),
            _agent("failed", tab="sase", status="FAILED"),
            done,
        ],
    )
    _install_tab_view(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _open_agents(page)
        # Manual unread marks survive the notification reconcile that
        # would clear a bare hand-set id, so the U badge is stable.
        page.app._manual_unread_agent_ids = {done.identity}
        page.app._unread_completed_agent_ids = {done.identity}
        page.app._update_agents_header()
        await wait_for_visual_idle(page)
        # Pump paint messages: settle helpers alone do not flush a
        # programmatic update into the composited frame.
        await page.pause(0.5)
        for token in ("S1", "F1", "U1"):
            await wait_for_svg_contains(page, token)
        ace_png_visual.assert_page_png(
            page,
            "agents_tab_strip_attention_120x40",
            title="ACE agents tab strip with attention badges",
        )


async def test_agents_tab_strip_overflow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(
        monkeypatch,
        agents=[
            _agent(f"worker-{idx:02d}", tab=f"project-{idx:02d}") for idx in range(16)
        ],
    )
    _install_tab_view(monkeypatch)
    async with AcePage(query='"visual"', patches=patches(), size=(80, 24)) as page:
        await _open_agents(page)
        await wait_for_svg_contains(page, "›")
        ace_png_visual.assert_page_png(
            page,
            "agents_tab_strip_overflow_80x24",
            title="ACE agents tab strip overflow at narrow width",
        )


async def test_agents_tab_strip_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = _agent("one")
    sase = _agent("two", tab="sase")
    patch_startup_loaders(monkeypatch, agents=[main, sase])
    _install_tab_view(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _open_agents(page)
        assert page.app._switch_agents_tab(_SASE, reason="visual") is True
        remaining = [
            row
            for row in page.app._agents_with_children
            if row.identity != sase.identity
        ]
        page.app._agents_with_children = remaining
        page.app._agents_query_result = list(remaining)
        page.app._refresh_agent_tab_index()
        page.app._rescope_agents_to_active_tab()
        page.app._refresh_agents_display(list_changed=True)
        page.app._refresh_agent_focus_detail()
        await wait_for_visual_idle(page)
        await page.pause(0.5)
        await wait_for_svg_contains(page, "No agents on")
        ace_png_visual.assert_page_png(
            page,
            "agents_tab_strip_empty_120x40",
            title="ACE agents tab strip genuinely empty tab",
        )


async def test_agents_tab_strip_query_hides_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(
        monkeypatch,
        agents=[_agent("one"), _agent("two", tab="sase")],
    )
    _install_tab_view(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _open_agents(page)
        # Drive the query through the real filter bar so the whole
        # pipeline (commit, refilter, rescope, detail) runs for real.
        await page.press("slash")
        for key in "tab:sase":
            await page.press(key)
        await page.press("enter")
        await wait_for_svg_contains(page, "hides")
        # Settle the keypress storm: late preview-worker results can
        # land one more display pass after the sentinel first paints.
        await wait_for_visual_idle(page)
        await page.pause(0.5)
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "agents_tab_strip_query_hides_120x40",
            title="ACE agents tab strip query hiding the active tab",
        )


async def test_agents_tab_strip_feed_unavailable_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.models._fleet_agents_hosts import HostFeedIssue

    apollo_key = AgentTabKey.machine("install-apollo")
    patch_startup_loaders(
        monkeypatch,
        agents=[
            _agent("one"),
            _agent(
                "remote",
                origin_alias="apollo",
                origin_id="install-apollo",
            ),
        ],
    )
    _install_tab_view(
        monkeypatch,
        machine_mode=True,
        machine_order=(("install-apollo", "apollo"),),
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _open_agents(page)
        assert page.app._switch_agents_tab(apollo_key, reason="visual") is True
        page.app._agents_fleet_projection = SimpleNamespace(
            host_feed_issues=(
                HostFeedIssue(
                    alias="apollo",
                    status="invalid",
                    error="handshake failed",
                    cache_age_seconds=None,
                    diagnostic=None,
                ),
            ),
            diagnostics=(),
        )
        page.app._agents_with_children = [
            row for row in page.app._agents_with_children if not row.fleet_origin_alias
        ]
        page.app._agents_query_result = list(page.app._agents_with_children)
        page.app._refresh_agent_tab_index()
        page.app._rescope_agents_to_active_tab()
        page.app._refresh_agents_display(list_changed=True)
        page.app._refresh_agent_focus_detail()
        await wait_for_visual_idle(page)
        await page.pause(0.5)
        await wait_for_svg_contains(page, "Machines")
        ace_png_visual.assert_page_png(
            page,
            "agents_tab_strip_feed_unavailable_120x40",
            title="ACE agents tab strip unavailable machine feed",
        )


async def test_agents_tab_strip_long_name_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    long_name = "a" * 32
    patch_startup_loaders(
        monkeypatch,
        agents=[_agent("one"), _agent("two", tab=long_name)],
    )
    _install_tab_view(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _open_agents(page)
        assert_page_svg_contains(page, long_name)
        ace_png_visual.assert_page_png(
            page,
            "agents_tab_strip_long_name_120x40",
            title="ACE agents tab strip with a 32-character name",
        )


async def test_agents_tab_strip_machine_mode_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(
        monkeypatch,
        agents=[
            _agent("one"),
            _agent("two", tab="sase"),
            _agent("remote", origin_alias="apollo", origin_id="install-apollo"),
            _agent("remote-mac", origin_alias="mac", origin_id="install-mac"),
        ],
    )
    _install_tab_view(
        monkeypatch,
        machine_mode=True,
        machine_order=(("install-apollo", "apollo"), ("install-mac", "mac")),
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _open_agents(page)
        for token in ("⌨", "local", "apollo", "mac", "sase", "┊"):
            await wait_for_svg_contains(page, token)
        ace_png_visual.assert_page_png(
            page,
            "agents_tab_strip_machine_mode_120x40",
            title="ACE agents tab strip in machine mode",
        )


async def test_agents_tab_strip_named_vs_machine_alias_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(
        monkeypatch,
        agents=[
            _agent("one"),
            _agent("named", tab="apollo"),
            _agent(
                "remote",
                origin_alias="apollo",
                origin_id="install-apollo",
            ),
        ],
    )
    _install_tab_view(
        monkeypatch,
        machine_mode=True,
        machine_order=(("install-apollo", "apollo"),),
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _open_agents(page)
        for token in ("⌨", "apollo"):
            await wait_for_svg_contains(page, token)
        ace_png_visual.assert_page_png(
            page,
            "agents_tab_strip_named_vs_machine_alias_120x40",
            title="ACE agents named apollo tab beside the apollo machine tab",
        )


async def test_agents_tab_strip_stale_host_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    apollo_key = AgentTabKey.machine("install-apollo")
    patch_startup_loaders(
        monkeypatch,
        agents=[
            _agent("one"),
            _agent(
                "remote",
                origin_alias="apollo",
                origin_id="install-apollo",
            ),
        ],
    )
    _install_tab_view(
        monkeypatch,
        machine_mode=True,
        machine_order=(("install-apollo", "apollo"),),
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _open_agents(page)
        assert page.app._switch_agents_tab(apollo_key, reason="visual") is True
        page.app._agents_fleet_projection = SimpleNamespace(
            host_feed_issues=(),
            diagnostics=({"alias": "apollo"},),
        )
        page.app._refresh_agent_tab_strip()
        page.app._update_agents_header()
        await wait_for_visual_idle(page)
        await page.pause(0.5)
        await wait_for_svg_contains(page, "apollo")
        ace_png_visual.assert_page_png(
            page,
            "agents_tab_strip_stale_host_120x40",
            title="ACE agents tab strip with a stale machine host",
        )


async def test_agents_tab_strip_by_machine_on_machine_tab_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The default tab is the ⌨ local machine tab in machine mode: its lone
    # `local` L0 banner is redundant with the strip, so only the Running
    # status subgroup renders.
    patch_startup_loaders(
        monkeypatch,
        agents=[
            _agent("one"),
            _agent("two", tab="sase"),
        ],
    )
    _install_tab_view(monkeypatch, machine_mode=True)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _open_agents(page)
        await page.press("o", "m")
        await wait_for_visual_idle(page)
        assert page.app._grouping_mode is GroupingMode.BY_MACHINE
        await page.pause(0.5)
        await wait_for_svg_contains(page, "Running")
        ace_png_visual.assert_page_png(
            page,
            "agents_tab_strip_by_machine_on_machine_tab_120x40",
            title="ACE agents BY_MACHINE on a machine tab",
        )


async def test_agents_tab_strip_by_machine_on_named_tab_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Named tabs keep the `local` machine banner and its status subgroups.
    patch_startup_loaders(
        monkeypatch,
        agents=[
            _agent("one"),
            _agent("two", tab="sase"),
        ],
    )
    _install_tab_view(monkeypatch, machine_mode=True)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _open_agents(page)
        assert page.app._switch_agents_tab(_SASE, reason="visual") is True
        await page.press("o", "m")
        await wait_for_visual_idle(page)
        assert page.app._grouping_mode is GroupingMode.BY_MACHINE
        await page.pause(0.5)
        await wait_for_svg_contains(page, "local")
        ace_png_visual.assert_page_png(
            page,
            "agents_tab_strip_by_machine_on_named_tab_120x40",
            title="ACE agents BY_MACHINE on a named tab",
        )


async def test_agents_tab_strip_picker_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(
        monkeypatch,
        agents=[
            _agent("one"),
            _agent("two", tab="sase"),
            _agent("three", tab="blog"),
        ],
    )
    _install_tab_view(monkeypatch)
    async with AcePage(query='"visual"', patches=patches()) as page:
        await _open_agents(page)
        page.app.action_pick_agents_tab()
        await wait_for_visual_idle(page)
        assert_page_svg_contains(page, "go to tab")
        ace_png_visual.assert_page_png(
            page,
            "agents_tab_strip_picker_120x40",
            title="ACE agents tab strip picker",
        )
