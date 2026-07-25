"""Loading and navigation coverage for the Artifacts Chats pane."""

from __future__ import annotations

from threading import Event

import pytest
from textual.widgets import OptionList

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts import chats_pane
from sase.ace.tui.widgets.artifacts.chats_pane import ArtifactsChatsPane
from tests.ace.tui._artifacts_chats_helpers import catalog, chat_entry
from tests.ace.tui._artifacts_plans_helpers import _choices


async def test_first_page_paints_before_full_extension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_entries = (
        chat_entry("newest", provenance="shared"),
        chat_entry(
            "older",
            mtime="2026-07-24T13:10:00-04:00",
            provenance="local",
        ),
    )
    full_entries = (
        *first_entries,
        chat_entry(
            "oldest",
            mtime="2026-07-23T09:00:00-04:00",
            provenance="remote",
            machine="zeus",
        ),
    )
    full_started = Event()
    release_full = Event()
    requested_limits: list[int | None] = []

    def load(**kwargs: object):
        limit = kwargs.get("limit")
        assert limit is None or isinstance(limit, int)
        requested_limits.append(limit)
        if limit is None:
            full_started.set()
            assert release_full.wait(timeout=5)
            return catalog(full_entries)
        return catalog(first_entries, truncated=True)

    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(chats_pane, "load_chat_catalog", load)

    try:
        async with AcePage(initial_tab="changespecs") as page:
            await page.press("3")
            pane = page.query_one_widget(
                "#artifacts-chats-pane",
                ArtifactsChatsPane,
            )
            await page.wait_for(
                lambda _state: (
                    pane.snapshot is not None and len(pane.snapshot.entries) == 2
                )
            )

            assert pane.selected_entry is first_entries[0]
            assert pane.entry_targets() == (
                ("chat", first_entries[0].absolute_path),
                ("chat", first_entries[1].absolute_path),
            )
            assert full_started.wait(timeout=2)
            assert requested_limits[:2] == [500, None]

            release_full.set()
            await page.wait_for(
                lambda _state: (
                    pane.snapshot is not None
                    and pane.snapshot.complete
                    and len(pane.snapshot.entries) == 3
                )
            )
            assert pane.selected_entry is first_entries[0]
    finally:
        release_full.set()


async def test_jk_navigation_skips_headers_without_highlight_echoes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = (
        chat_entry("first", provenance="shared"),
        chat_entry(
            "second",
            mtime="2026-07-24T13:10:00-04:00",
            provenance="unknown",
        ),
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        chats_pane,
        "load_chat_catalog",
        lambda **_kwargs: catalog(entries),
    )

    async with AcePage(initial_tab="changespecs") as page:
        await page.press("3")
        pane = page.query_one_widget("#artifacts-chats-pane", ArtifactsChatsPane)
        await page.wait_for(lambda _state: pane.selected_entry is entries[0])
        option_list = pane.query_one("#chats-list", OptionList)
        assert option_list.highlighted == 1

        await page.press("j")
        assert pane.selected_entry is entries[1]
        await page.press("k")
        assert pane.selected_entry is entries[0]

        assert pane.select_entry_target(("chat", entries[1].absolute_path))
        assert pane.selected_entry is entries[1]
