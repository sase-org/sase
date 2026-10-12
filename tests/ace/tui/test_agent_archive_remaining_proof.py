"""Mounted remaining-proof regressions (child-epic phase ``remaining-proof``).

Each test drives a real ``AceApp`` through the user-visible path of a defect
fixed by an earlier phase of this child epic, so the seams meet the way the
TUI uses them. Unit coverage for each seam lives in its own module; these
tests prove the mounted wiring:

- Inbox detail repaints after an Archive round trip (detail-ownership #1)
- hidden Inbox refresh preserves Archive hydration (detail-ownership #2)
- copy on a banner reads nothing, never the parked Inbox (action-boundary #2)
- the stuck loading card clears when the cursor leaves a run (detail #4/#5)
- Archive marks render and the footer syncs (action-boundary #6/#7)
- deck splits survive an Archive round trip (parking-and-import #1)

The closing test pins the beta-off contract: with the flag off the Archive
never mounts and every guard passes through to the Inbox.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions.agents._archive_actions import (
    archive_marked_run_keys,
    archive_read_target,
    guard_archive_live_action,
    resolve_agents_read_agent,
    toggle_archive_mark,
)
from sase.ace.tui.actions.agents._archive_controller import (
    note_inbox_applied_for_archive,
)
from sase.ace.tui.actions.agents._archive_reader import arm_archive_detail_hydration
from sase.ace.tui.actions.agents._archive_view import (
    archive_detail_owns_panel,
    close_agents_archive_view,
    open_agents_archive_view,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_archive_view import AGENTS_VIEW_INBOX
from sase.ace.tui.widgets.agents_archive import ArchiveList
from sase.feature_flags import override_flags
from tests.ace.tui._agent_archive_column_helpers import (
    ModelCorpus,
    complete_load,
    light_row,
    tokens,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patch_startup_loaders,
    wait_for_startup,
)


def _inbox_agent(name: str = "live-agent") -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="crs",
        raw_suffix="20260527120000",
        agent_name="live.agent",
    )


def _history() -> list[dict[str, Any]]:
    rows = [
        light_row(f"t{i:02d}", day="2026-10-10", hour=23 - i, name=f"today.{i:02d}")
        for i in range(6)
    ]
    rows += [
        light_row(f"y{i:02d}", day="2026-10-09", hour=22 - i, name=f"yday.{i:02d}")
        for i in range(4)
    ]
    return rows


def _wire_corpus(app: Any, corpus: ModelCorpus) -> None:
    from tests.ace.tui._agent_archive_column_helpers import NOW

    app._archive_get_corpus = lambda **kwargs: SimpleNamespace(
        corpus=corpus, profile=SimpleNamespace(digest="profile-1")
    )
    app._archive_probe_tokens = lambda: tokens()
    app._archive_load_facets = lambda: {}
    app._archive_profile = SimpleNamespace(digest="profile-1")
    app._archive_now = lambda: NOW


async def _wait_for_rows(page: AcePage) -> None:
    await page.wait_for(
        lambda _state: (
            "u.m@t00"
            in (
                page.app.query_one("#archive-list", ArchiveList).item_keys
                if page.app.query("#archive-list")
                else ()
            )
        ),
        timeout=10.0,
    )


def _prompt(archive_list: ArchiveList, key: str) -> str:
    prompt = archive_list.get_option(key).prompt
    return str(getattr(prompt, "plain", prompt))


async def test_mounted_inbox_detail_repaints_after_archive_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inbox j/k repaints detail after an Archive visit (detail-ownership #1)."""
    patch_startup_loaders(
        monkeypatch, agents=[_inbox_agent("inbox.zero"), _inbox_agent("inbox.one")]
    )
    with override_flags(agents_archive_view=True):
        async with AcePage(initial_tab="agents", size=(160, 40)) as page:
            await wait_for_startup(page)
            app = page.app
            _wire_corpus(app, ModelCorpus(_history()))
            note_inbox_applied_for_archive(app, load_state=complete_load())

            open_agents_archive_view(app)
            await _wait_for_rows(page)
            close_agents_archive_view(app)
            await page.pause()
            assert not archive_detail_owns_panel(app)
            assert app._agents_archive_view.active_view == AGENTS_VIEW_INBOX

            await page.press("j")
            await page.pause(0.5)

            assert app.current_idx == 1
            scheduled = app._agents_detail_scheduled_owner
            assert scheduled is not None
            assert scheduled.view == AGENTS_VIEW_INBOX


async def test_mounted_hidden_inbox_refresh_preserves_archive_hydration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hidden Inbox focus refresh never steals Archive hydration (detail #2)."""
    patch_startup_loaders(monkeypatch, agents=[_inbox_agent()])
    with override_flags(agents_archive_view=True):
        async with AcePage(initial_tab="agents", size=(160, 40)) as page:
            await wait_for_startup(page)
            app = page.app
            _wire_corpus(app, ModelCorpus(_history()))
            note_inbox_applied_for_archive(app, load_state=complete_load())
            open_agents_archive_view(app)
            await _wait_for_rows(page)

            schedules: list[Any] = []
            debouncer = app._agent_detail_debouncer
            original_schedule = debouncer.schedule

            def _counting_schedule(callback: Any) -> None:
                schedules.append(callback)
                original_schedule(callback)

            monkeypatch.setattr(debouncer, "schedule", _counting_schedule)
            arm_archive_detail_hydration(app)
            armed = len(schedules)
            assert armed >= 1

            # The hidden path a theme/fleet/startup caller takes must not
            # cancel or replace the Archive's pending hydration.
            app._refresh_agent_focus_detail(render_immediate=True)
            app._refresh_agent_focus_detail(render_immediate=False)

            assert len(schedules) == armed
            assert debouncer.is_pending
            assert archive_detail_owns_panel(app)


async def test_mounted_copy_on_banner_reads_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Copy on an Archive banner notifies instead of copying Inbox (boundary #2)."""
    patch_startup_loaders(monkeypatch, agents=[_inbox_agent()])
    with override_flags(agents_archive_view=True):
        async with AcePage(initial_tab="agents", size=(160, 40)) as page:
            await wait_for_startup(page)
            app = page.app
            _wire_corpus(app, ModelCorpus(_history()))
            note_inbox_applied_for_archive(app, load_state=complete_load())
            inbox_agent = app._get_selected_agent()
            open_agents_archive_view(app)
            await _wait_for_rows(page)

            await page.press("g")
            await page.pause()
            selected = app._agents_archive_view.archive.selected_key
            assert selected is not None and not selected.startswith("u.m@")

            assert archive_read_target(app) is None
            assert resolve_agents_read_agent(app) is None

            delivered: list[str] = []
            notices: list[str] = []
            monkeypatch.setattr(
                "sase.ace.tui.actions.clipboard._agents.schedule_copy_delivery",
                lambda _owner, content, **_kwargs: delivered.append(content),
            )
            monkeypatch.setattr(
                app, "notify", lambda message, *_a, **_k: notices.append(message)
            )
            app._copy_agent_name()
            await page.pause()

            assert delivered == []
            assert notices == ["No agent selected"]
            assert app._get_selected_agent() is inbox_agent


async def test_mounted_stuck_loading_card_clears_on_pulse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Leaving an Archive run for the pulse never sticks the loading card."""
    from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import page_svg_text

    patch_startup_loaders(monkeypatch, agents=[_inbox_agent()])
    with override_flags(agents_archive_view=True):
        async with AcePage(initial_tab="agents", size=(160, 40)) as page:
            await wait_for_startup(page)
            app = page.app
            _wire_corpus(app, ModelCorpus(_history()))
            note_inbox_applied_for_archive(app, load_state=complete_load())
            open_agents_archive_view(app)
            await _wait_for_rows(page)
            await page.pause(1.0)

            await page.press("J")
            await page.pause(1.0)

            text = page_svg_text(page)
            assert "Loading archived run" not in text


async def test_mounted_marks_render_and_footer_syncs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Archive m/M marks draw with Inbox style and the footer follows (#6/#7)."""
    from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import page_svg_text

    patch_startup_loaders(monkeypatch, agents=[_inbox_agent()])
    with override_flags(agents_archive_view=True):
        async with AcePage(initial_tab="agents", size=(160, 40)) as page:
            await wait_for_startup(page)
            app = page.app
            _wire_corpus(app, ModelCorpus(_history()))
            note_inbox_applied_for_archive(app, load_state=complete_load())
            open_agents_archive_view(app)
            await _wait_for_rows(page)

            await page.press("m")
            await page.pause()
            assert archive_marked_run_keys(app) == frozenset({"u.m@t00"})
            archive_list = app.query_one("#archive-list", ArchiveList)
            assert "[✓]" in _prompt(archive_list, "u.m@t00")
            assert "unmark (1)" in page_svg_text(page)

            await page.press("u")
            await page.pause()
            assert archive_marked_run_keys(app) == frozenset()
            assert "[✓]" not in _prompt(archive_list, "u.m@t00")
            assert "unmark" not in page_svg_text(page)


async def test_mounted_deck_splits_survive_archive_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An Archive round trip never reverts the shared deck splits (parking #1)."""
    from sase.ace.tui.widgets import AgentDetail

    patch_startup_loaders(monkeypatch, agents=[_inbox_agent()])
    with override_flags(agents_archive_view=True):
        async with AcePage(initial_tab="agents", size=(160, 40)) as page:
            await wait_for_startup(page)
            app = page.app
            _wire_corpus(app, ModelCorpus(_history()))
            note_inbox_applied_for_archive(app, load_state=complete_load())

            await page.press("vertical_line")
            await page.pause()
            detail = app.query_one("#agent-detail-panel", AgentDetail)
            # Splits live in the grid (panes, axis, ratios); per-panel deck
            # and card choices are parked separately and may round-trip.
            before = (detail.deck_area.state.layout, repr(detail.deck_area.state.grid))
            assert before[0].name != "SINGLE"

            open_agents_archive_view(app)
            await _wait_for_rows(page)
            # Change splits while Archive owns the panel. Restore must keep
            # this live grid, not reapply the parked Inbox snapshot.
            await page.press("backslash")
            await page.pause()
            inside_detail = app.query_one("#agent-detail-panel", AgentDetail)
            inside = (
                inside_detail.deck_area.state.layout,
                repr(inside_detail.deck_area.state.grid),
            )
            assert inside != before
            close_agents_archive_view(app)
            await page.pause()

            after_state = app.query_one(
                "#agent-detail-panel", AgentDetail
            ).deck_area.state
            assert (after_state.layout, repr(after_state.grid)) == inside


async def test_mounted_beta_off_guards_leave_inbox_intact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the beta off the Archive never mounts and guards pass through."""
    patch_startup_loaders(
        monkeypatch, agents=[_inbox_agent("inbox.zero"), _inbox_agent("inbox.one")]
    )
    with override_flags():
        async with AcePage(initial_tab="agents", size=(160, 40)) as page:
            await wait_for_startup(page)
            app = page.app

            assert open_agents_archive_view(app).status == "disabled"
            assert guard_archive_live_action(app, "kill_agent") is False
            assert toggle_archive_mark(app) is False
            assert archive_read_target(app) is None
            assert resolve_agents_read_agent(app) is app._get_selected_agent()

            await page.press("j")
            await page.pause()
            assert app.current_idx == 1
            assert app._agents_archive_view.active_view == AGENTS_VIEW_INBOX

            await page.press("comma")
            await page.press("a")
            await page.pause()
            assert app._agents_archive_view.active_view == AGENTS_VIEW_INBOX


async def test_quitting_from_archive_persists_inbox_query_and_grouping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.grouping_strategy import (
        load_agent_archive_grouping,
        save_agent_archive_grouping,
    )
    from sase.ace.tui.models import agent_query_persistence as store
    from tests._conftest_environment import redirect_sase_home

    home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    save_agent_archive_grouping("project")
    patch_startup_loaders(monkeypatch, agents=[_inbox_agent()])
    with override_flags(agents_archive_view=True):
        async with AcePage(initial_tab="agents", size=(160, 40)) as page:
            await wait_for_startup(page)
            app = page.app
            _wire_corpus(app, ModelCorpus(_history()))
            note_inbox_applied_for_archive(app, load_state=complete_load())
            app._record_explicit_agents_query_commit("status:FAILED")
            open_agents_archive_view(app)
            await _wait_for_rows(page)
            await app._flush_agents_query_state()

    loaded = store.load_agent_query_snapshot(active_dialect=store.DIALECT_UNIFIED)
    assert loaded.snapshot is not None
    assert loaded.snapshot.record.source == "status:FAILED"
    assert load_agent_archive_grouping() == "project"
    assert (home / "ace_agents_last_query.json").exists()
    assert (home / "agent_archive_grouping.txt").read_text(
        encoding="utf-8"
    ).strip() == ("project")
