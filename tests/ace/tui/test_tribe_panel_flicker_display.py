"""Tribe panel flicker: display memoization and deck stability."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.ace.tui.models.agent_tribe_summary import build_agent_tribe_summary_snapshot
from tests.ace.tui._tribe_panel_flicker_helpers import (
    FLICKER_NOW,
    make_tribe_flicker_agent,
)


def test_update_tribe_display_memo_skips_identical_rebuild(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from textual.app import App, ComposeResult

    from sase.ace.tui.models.fold_state import FoldLevel
    from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel

    agent = make_tribe_flicker_agent("memo", "memo")
    snapshot = build_agent_tribe_summary_snapshot(
        "epic", [agent], panel_collapsed=True, now=FLICKER_NOW
    )

    builds: list[str] = []
    real_builder: Any = None
    try:
        from sase.ace.tui.widgets.prompt_panel import _agent_display_tribe as tribe_mod

        real_builder = tribe_mod.build_tribe_detail_text

        def counting_builder(*args: Any, **kwargs: Any) -> Any:
            builds.append("built")
            return real_builder(*args, **kwargs)

        monkeypatch.setattr(tribe_mod, "build_tribe_detail_text", counting_builder)
    except Exception:
        pass

    class _MemoApp(App[None]):
        def compose(self) -> ComposeResult:
            yield AgentPromptPanel(id="agent-prompt-panel")

    app = _MemoApp()
    import asyncio

    async def _run() -> None:
        async with app.run_test(size=(80, 24)) as pilot:
            panel = app.query_one("#agent-prompt-panel", AgentPromptPanel)
            panel.update_tribe_display(snapshot, cheap=False)
            await pilot.pause()
            first_builds = len(builds)
            assert first_builds == 1

            panel.update_tribe_display(snapshot, cheap=False)
            await pilot.pause()
            assert len(builds) == first_builds

            panel.update_display(agent)
            await pilot.pause()
            panel.update_tribe_display(snapshot, cheap=False)
            await pilot.pause()
            assert len(builds) == first_builds + 1

    asyncio.run(_run())


async def test_selected_tribe_noop_refresh_keeps_main_deck_stable() -> None:
    """Pilot regression: idle finalize refresh must not repaint a placeholder."""
    from sase.ace.tui.app import AceApp
    from sase.ace.tui.models.fold_state import FoldLevel
    from sase.ace.tui.widgets.agent_detail import AgentDetail as _Detail
    from sase.ace.tui.widgets.agent_jump_panel import AgentJumpPanel
    from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
    from sase.ace.tui.widgets.renderable_text import renderable_to_text
    from tests.ace.tui._bench_tui_jk_helpers import (
        _install_agents_fixture,
        _wait_for_startup,
    )

    app = AceApp(query="!!!", auto_start_axe=False, refresh_interval=0)
    async with app.run_test(size=(120, 40)) as pilot:
        await _wait_for_startup(app, pilot)
        await pilot.press("ctrl+l")
        await pilot.pause()
        _install_agents_fixture(app, count=48)
        app._refresh_agents_display(list_changed=True, defer_detail=True)
        await pilot.pause(0.2)
        assert app._activate_focused_panel() is True
        assert app._resolve_focused_panel() is not None
        await pilot.press("z", "z")
        await pilot.pause(0.3)
        app._fire_debounced_detail_update()
        await pilot.pause(0.4)
        detail = app.query_one("#agent-detail-panel", _Detail)
        detail.query_one("#agent-prompt-panel", AgentPromptPanel)
        jump = detail.query_one("#agent-jump-panel", AgentJumpPanel)
        assert jump.has_targets
        assert not jump.has_class("hidden")

        try:
            scroll = detail.deck_area.focused_panel().active_scroll()
        except Exception:
            scroll = None
        if scroll is not None:
            try:
                scroll.scroll_to(y=40, animate=False)
            except Exception:
                pass
            await pilot.pause(0.2)
            before_y = int(scroll.scroll_y)
        else:
            before_y = 0
        before_targets = len(jump._jump_map.targets) if jump._jump_map else 0
        assert before_targets > 0

        paints: list[str] = []
        real_update = AgentPromptPanel.update

        def recording_update(self: Any, content: Any = "", **kwargs: Any) -> None:
            try:
                paints.append(renderable_to_text(content) or "")
            except Exception:
                paints.append("")
            real_update(self, content, **kwargs)

        jump_events: list[tuple[int, bool]] = []
        real_show_jump = AgentJumpPanel.show_jump_map

        def recording_show_jump(self: Any, jump_map: Any, roster: Any = None) -> None:
            try:
                jump_events.append(
                    (
                        len(jump_map.targets) if jump_map is not None else 0,
                        self.has_class("hidden"),
                    )
                )
            except Exception:
                pass
            real_show_jump(self, jump_map, roster)

        import unittest.mock as mock

        with mock.patch.object(AgentPromptPanel, "update", recording_update):
            with mock.patch.object(
                AgentJumpPanel, "show_jump_map", recording_show_jump
            ):
                app._refresh_agents_display_after_finalize(
                    previous_agents=list(app._agents), defer_detail=True
                )
                await pilot.pause(0.5)
                app._refresh_agents_display(list_changed=True, defer_detail=True)
                await pilot.pause(0.5)

        assert not any("loading" in paint for paint in paints), (
            f"placeholder repainted: {[p[:80] for p in paints if 'loading' in p]}"
        )
        assert jump.has_targets
        assert not jump.has_class("hidden")
        assert all(count > 0 for count, _hidden in jump_events), (
            f"jump panel lost targets: {jump_events}"
        )
        if scroll is not None:
            assert int(scroll.scroll_y) == before_y


def test_update_tribe_display_rebuilds_on_theme_change(
    tmp_path: Path, monkeypatch: Any
) -> None:
    from textual.app import App, ComposeResult

    from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel

    agent = make_tribe_flicker_agent("theme", "theme")
    snapshot = build_agent_tribe_summary_snapshot(
        "epic", [agent], panel_collapsed=True, now=FLICKER_NOW
    )
    builds: list[str] = []
    try:
        from sase.ace.tui.widgets.prompt_panel import _agent_display_tribe as tribe_mod

        real_builder = tribe_mod.build_tribe_detail_text

        def counting_builder(*args: Any, **kwargs: Any) -> Any:
            builds.append("built")
            return real_builder(*args, **kwargs)

        monkeypatch.setattr(tribe_mod, "build_tribe_detail_text", counting_builder)
    except Exception:
        pass

    class _ThemeApp(App[None]):
        def compose(self) -> ComposeResult:
            yield AgentPromptPanel(id="agent-prompt-panel")

    app = _ThemeApp()
    import asyncio

    async def _run() -> None:
        async with app.run_test(size=(80, 24)) as pilot:
            panel = app.query_one("#agent-prompt-panel", AgentPromptPanel)
            panel.update_tribe_display(snapshot, cheap=False)
            await pilot.pause()
            assert len(builds) == 1
            monkeypatch.setattr(panel, "_tribe_theme_name", lambda: "other-theme")
            panel.update_tribe_display(snapshot, cheap=False)
            await pilot.pause()
            assert len(builds) == 2

    asyncio.run(_run())
