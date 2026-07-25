"""Inline filtering, summary chips, cycling, and preview for Chats."""

from __future__ import annotations

from dataclasses import replace

import pytest
from textual.widgets import OptionList, Static

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts import chats_pane
from sase.ace.tui.widgets.artifacts.chat_filter_bar import ChatFilterBar
from sase.ace.tui.widgets.artifacts.chats_data import ChatsSnapshot
from sase.ace.tui.widgets.artifacts.chats_filtering import filter_chats_snapshot
from sase.ace.tui.widgets.artifacts.chats_pane import ArtifactsChatsPane
from sase.history.chat_filter_query import (
    ChatFilterQueryError,
    parse_chat_filter_query,
)
from tests.ace.tui._artifacts_chats_helpers import catalog, chat_entry
from tests.ace.tui._artifacts_plans_helpers import _choices


def test_filter_tokens_match_catalog_fields() -> None:
    entry = replace(
        chat_entry("needle", provenance="remote", machine="zeus"),
        workflow="review",
        project_key="bob",
        agent_local_name="bob.foo--review",
        prompt_snippet="Inspect the retry queue",
    )
    snapshot = ChatsSnapshot(
        project="bob",
        catalog=catalog((entry,)),
        complete=True,
    )
    matched = filter_chats_snapshot(
        snapshot,
        parse_chat_filter_query(
            "provenance:remote machine:zeus project:bob "
            "agent:bob.foo--review workflow:review retry"
        ),
    )
    excluded = filter_chats_snapshot(
        snapshot,
        parse_chat_filter_query("provenance:shared"),
    )
    assert matched is not None and matched.entries == (entry,)
    assert excluded is not None and not excluded.entries


@pytest.mark.parametrize(
    "query",
    [
        "provenance:bogus",
        "unknown:value",
        "since:tomorrow until:yesterday",
    ],
)
def test_invalid_filter_tokens_are_rejected(query: str) -> None:
    with pytest.raises(ChatFilterQueryError):
        parse_chat_filter_query(query)


async def test_filter_bar_and_provenance_cycle_update_rows_and_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries = (
        chat_entry("local", provenance="local"),
        chat_entry("shared", provenance="shared"),
        chat_entry("remote", provenance="remote", machine="zeus"),
        chat_entry("unknown", provenance="unknown"),
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
        await page.press("5")
        pane = page.query_one_widget("#artifacts-chats-pane", ArtifactsChatsPane)
        await page.wait_for(lambda _state: pane.snapshot is not None)
        info = pane.query_one("#chats-info", Static)
        assert "◇ 1 local" in info.content.plain
        assert "◆ 1 shared" in info.content.plain
        assert "↓ 1 remote (1 machine)" in info.content.plain
        assert "○ 1 unknown" in info.content.plain

        bar = pane.query_one(ChatFilterBar)
        await page.press("f")
        await page.wait_for(lambda _state: bar.display)
        await page.press(*tuple("provenance:remote"))
        await page.wait_for(lambda _state: pane.selected_entry is entries[2])
        assert len(pane.entry_targets()) == 1
        await page.press("enter")
        await page.wait_for(lambda _state: not bar.display)
        assert pane.filters.provenances == ("remote",)

        expected = ("unknown", None, "local", "shared", "remote")
        for provenance in expected:
            await page.press("s")
            await page.wait_for(
                lambda _state, value=provenance: (
                    pane.filters.provenances == (() if value is None else (value,))
                )
            )
        options = pane.query_one("#chats-list", OptionList)
        assert options.option_count == 2


async def test_enter_pushes_full_transcript_preview(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transcript = tmp_path / "selected.md"
    transcript.write_text("# Full transcript\n\nComplete body.", encoding="utf-8")
    entry = replace(
        chat_entry("selected", provenance="shared"),
        absolute_path=str(transcript),
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        chats_pane,
        "load_chat_catalog",
        lambda **_kwargs: catalog((entry,)),
    )

    async with AcePage(initial_tab="changespecs") as page:
        await page.press("5")
        pane = page.query_one_widget("#artifacts-chats-pane", ArtifactsChatsPane)
        await page.wait_for(lambda _state: pane.selected_entry is entry)
        await page.press("enter")
        await page.expect_modal("PreviewPanelModal")
