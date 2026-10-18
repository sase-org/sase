"""Archive column in the mounted ``AceApp``: lazy mount, CSS, and key routing."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions.agents._archive_controller import (
    note_inbox_applied_for_archive,
)
from sase.ace.tui.actions.agents._archive_view import (
    close_agents_archive_view,
    open_agents_archive_view,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_archive_view import (
    AGENTS_VIEW_INBOX,
    ARCHIVE_SECTION_PULSE,
)
from sase.ace.tui.widgets.agents_archive import ArchiveColumn, ArchiveList, ArchivePulse
from sase.feature_flags import override_flags
from tests.ace.tui._agent_archive_column_helpers import (
    NOW,
    ModelCorpus,
    complete_load,
    light_row,
    tokens,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patch_startup_loaders,
    wait_for_startup,
)


def _inbox_agent() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="live-agent",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="crs",
        raw_suffix="20260527120000",
        agent_name="live.agent",
    )


def _history() -> list[dict[str, Any]]:
    rows = [
        light_row(
            f"t{i:02d}", day="2026-10-10", hour=23 - i % 12, name=f"today.{i:02d}"
        )
        for i in range(30)
    ]
    rows += [
        light_row(f"y{i:02d}", day="2026-10-09", hour=22 - i % 12, name=f"yday.{i:02d}")
        for i in range(30)
    ]
    rows += [
        light_row(f"w{i:02d}", day="2026-09-20", hour=12, name=f"old.{i:02d}")
        for i in range(10)
    ]
    return rows


def _wire_corpus(app: Any, corpus: ModelCorpus) -> None:
    app._archive_get_corpus = lambda **kwargs: SimpleNamespace(
        corpus=corpus, profile=SimpleNamespace(digest="profile-1")
    )
    app._archive_probe_tokens = lambda: tokens()
    app._archive_load_facets = lambda: {}
    app._archive_profile = SimpleNamespace(digest="profile-1")
    app._archive_now = lambda: NOW


def _list_keys(app: Any) -> tuple[str, ...]:
    return app.query_one("#archive-list", ArchiveList).item_keys


def _archive_expand_timeout(app: Any, *, timeout: float = 5.0) -> str:
    """Timeout text for the Today-banner expand wait: archive + controller."""
    view = getattr(app, "_agents_archive_view", None)
    archive = getattr(view, "archive", None) if view is not None else None
    controller = getattr(app, "_agents_archive_controller", None)
    return (
        f"wait_for() timed out after {timeout}s — archive"
        f" selected_key={getattr(archive, 'selected_key', None)!r}"
        f" focused_section={getattr(archive, 'focused_section', None)!r}"
        f" folded_banners={getattr(archive, 'folded_banners', None)!r}"
        f" generation={getattr(controller, 'generation', None)!r}"
        f" refreshing={getattr(controller, 'refreshing', None)!r}"
        f" status={getattr(controller, 'status', None)!r}"
    )


def _prompt(archive_list: ArchiveList, key: str) -> str:
    prompt = archive_list.get_option(key).prompt
    return str(getattr(prompt, "plain", prompt))


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


async def test_open_mounts_the_archive_column_without_a_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[_inbox_agent()])
    with override_flags():
        async with AcePage(initial_tab="agents", size=(160, 40)) as page:
            await wait_for_startup(page)
            app = page.app
            _wire_corpus(app, ModelCorpus(_history()))
            note_inbox_applied_for_archive(app, load_state=complete_load())

            assert open_agents_archive_view(app).status == "opened"
            await _wait_for_rows(page)

            assert app.query_one("#agents-content").has_class("-archive-active")
            assert app.query_one("#archive-column", ArchiveColumn).display
            assert not app.query_one("#agent-list-container").display


async def test_archive_replaces_the_inbox_column_and_keys_navigate_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[_inbox_agent()])
    async with AcePage(initial_tab="agents", size=(160, 40)) as page:
        await wait_for_startup(page)
        app = page.app
        _wire_corpus(app, ModelCorpus(_history()))
        note_inbox_applied_for_archive(app, load_state=complete_load())
        inbox_idx = app.current_idx
        inbox_agents = list(app._agents)

        open_agents_archive_view(app)
        await _wait_for_rows(page)

        content = app.query_one("#agents-content")
        assert content.has_class("-archive-active")
        assert app.query_one("#archive-column", ArchiveColumn).display
        assert not app.query_one("#agent-list-container").display
        archive_list = app.query_one("#archive-list", ArchiveList)
        keys = archive_list.item_keys
        assert _prompt(archive_list, "banner:day:2026-10-10").startswith("▾ Today")
        assert _prompt(archive_list, "banner:day:2026-10-09").startswith("▾ Yesterday")
        row = _prompt(archive_list, "u.m@t00")
        assert "today.00" in row and "✓ done" in row
        assert "⌂ Inbox" in str(app.query_one("#archive-pulse").render())
        assert keys[0] == "banner:day:2026-10-10"
        assert archive_list.highlighted == keys.index("u.m@t00")

        await page.press("j")
        assert archive_list.highlighted == keys.index("u.m@t01")
        assert app._agents_archive_view.archive.selected_key == "u.m@t01"
        await page.press("k", "k")
        assert archive_list.highlighted == 0  # banner
        await page.press("G")
        assert archive_list.highlighted == len(keys) - 1
        await page.press("g")
        assert archive_list.highlighted == 0

        # `h` folds Today, `l` opens it again; Enter on the banner toggles.
        await page.press("h")
        await page.pause()
        assert "banner:day:2026-10-10" in _list_keys(app)
        assert "u.m@t00" not in _list_keys(app)
        await page.press("l")
        await page.wait_for(
            lambda _s: "u.m@t00" in _list_keys(app),
            timeout_message=lambda: _archive_expand_timeout(app),
        )
        await page.press("enter")
        await page.pause()
        assert "u.m@t00" not in _list_keys(app)
        await page.press("enter")
        await page.wait_for(
            lambda _s: "u.m@t00" in _list_keys(app),
            timeout_message=lambda: _archive_expand_timeout(app),
        )

        # The Inbox is parked, never navigated.
        assert app.current_idx == inbox_idx
        assert app._agents == inbox_agents


async def test_J_switches_to_the_pulse_and_enter_returns_to_the_inbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[_inbox_agent()])
    async with AcePage(initial_tab="agents", size=(160, 40)) as page:
        await wait_for_startup(page)
        app = page.app
        _wire_corpus(app, ModelCorpus(_history()))
        note_inbox_applied_for_archive(app, load_state=complete_load())
        open_agents_archive_view(app)
        await _wait_for_rows(page)

        await page.press("J")
        pulse = app.query_one("#archive-pulse", ArchivePulse)
        assert pulse.has_class("-selected")
        assert app._agents_archive_view.archive.focused_section == ARCHIVE_SECTION_PULSE
        await page.press("enter")
        await page.wait_for(
            lambda _s: app._agents_archive_view.active_view == AGENTS_VIEW_INBOX,
            timeout_message=lambda: (
                "wait_for() timed out waiting for Inbox after pulse Enter —"
                f" active_view={app._agents_archive_view.active_view!r}"
                f" focused_section={app._agents_archive_view.archive.focused_section!r}"
                f" pulse_selected={pulse.has_class('-selected')}"
            ),
        )
        content = app.query_one("#agents-content")
        assert not content.has_class("-archive-active")
        assert app.query_one("#agent-list-container").display
        assert not app.query_one("#archive-column").display

        # Reopening reuses the mounted column and lands back on the list.
        open_agents_archive_view(app)
        await _wait_for_rows(page)
        assert not app.query_one("#archive-pulse", ArchivePulse).has_class("-selected")
        assert len(app.query("#archive-column")) == 1

        close_agents_archive_view(app)
        await page.pause()
        assert app.query_one("#agent-list-container").display


async def test_clicking_the_pulse_returns_to_the_inbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[_inbox_agent()])
    async with AcePage(initial_tab="agents", size=(160, 40)) as page:
        await wait_for_startup(page)
        app = page.app
        _wire_corpus(app, ModelCorpus(_history()))
        note_inbox_applied_for_archive(app, load_state=complete_load())
        open_agents_archive_view(app)
        await _wait_for_rows(page)

        await page.click("#archive-pulse")
        await page.pause()

        assert app._agents_archive_view.active_view == AGENTS_VIEW_INBOX


async def test_clicking_a_banner_toggles_it_like_enter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[_inbox_agent()])
    async with AcePage(initial_tab="agents", size=(160, 40)) as page:
        await wait_for_startup(page)
        app = page.app
        _wire_corpus(app, ModelCorpus(_history()))
        note_inbox_applied_for_archive(app, load_state=complete_load())
        open_agents_archive_view(app)
        await _wait_for_rows(page)

        await page.click("#archive-list", offset=(4, 1))  # the Today banner
        await page.pause()

        assert "u.m@t00" not in _list_keys(app)
        await page.click("#archive-list", offset=(4, 1))
        await page.wait_for(lambda _s: "u.m@t00" in _list_keys(app))


async def test_live_only_archive_keys_reach_their_toast_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch, agents=[_inbox_agent()])
    async with AcePage(initial_tab="agents", size=(160, 40)) as page:
        await wait_for_startup(page)
        app = page.app
        open_agents_archive_view(app)
        notices: list[str] = []

        def capture_notice(message: str, *_args: Any, **_kwargs: Any) -> None:
            notices.append(message)

        monkeypatch.setattr(app, "notify", capture_notice)
        app.bind(
            "ctrl+f12",
            "pick_agents_tab",
            description="Pick agent tabs",
            show=False,
        )

        for key in (
            "x",
            "X",
            "s",
            "S",
            "w",
            "W",
            "A",
            "R",
            "n",
            "N",
            "U",
            "[",
            "]",
            "ctrl+f12",
        ):
            before = len(notices)
            await page.press(key)
            assert len(notices) == before + 1, key
            assert ",a" in notices[-1], key
