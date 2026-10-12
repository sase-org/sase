"""sase's TUI PNG visual snapshots for the ≡ RECORD deck (epic sase-1jm.4.2, ``proof``).

Deterministic goldens for every Record selection shape: Lifecycle on an
inbox agent, Links on an agent with artifact links in both directions,
Lifecycle on a hydrated archived agent (slate chrome inside the amber
Archive), and Record on an unreadable archive entry. Templates are
``show_final()`` in ``_ace_agents_final_png_snapshot_shared`` and the
``_wire`` / ``light_row`` / ``_write_reply_bundle`` /
former feature-flag wrappers in
``test_ace_png_snapshots_agents_archive``. Time is pinned with
``pin_agents_visual_now``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions.agents._archive_controller import (
    note_inbox_applied_for_archive,
)
from sase.ace.tui.actions.agents._archive_view import open_agents_archive_view
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_archive_controller import ArchiveRevalidationTokens
from sase.ace.tui.widgets import AgentDetail
from sase.ace.tui.widgets.agents_archive import ArchiveList
from sase.ace.tui.widgets.decks.model import DeckId
from sase.feature_flags import override_flags
from tests.ace.tui._agent_archive_column_helpers import (
    ModelCorpus,
    complete_load,
    light_row,
)
from tests.ace.tui.visual._ace_agents_final_png_snapshot_shared import (
    deck_summary,
    goto_agents,
    make_agent,
    pin_visual_time,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
    page_svg_text,
    pin_agents_visual_now,
    pin_decks_paged,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture
from tests.ace.tui.widgets._agent_display_helpers import (
    make_agent as make_archive_agent,
)

pytestmark = pytest.mark.visual

NOW = datetime(2026, 10, 10, 20, 0, tzinfo=UTC)


async def show_record(
    page: AcePage,
    *,
    preferred: str | None = None,
    index: int = 0,
    expect: str | None = None,
) -> AgentDetail:
    """Show the RECORD deck on one panel and wait for its document to paint."""
    from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import page_svg_text

    detail = page.app.query_one("#agent-detail-panel", AgentDetail)
    if preferred is not None:
        detail.set_deck_preferred_card(index, preferred, DeckId.RECORD)
    detail.show_deck(index, DeckId.RECORD)
    await wait_for_state(
        page,
        lambda: bool(detail.deck_area.panel(index)._record_document.cards),
        description="RECORD deck document loaded",
    )
    if expect is not None:
        compact = expect.replace(" ", "")

        def _painted(_state: dict[str, Any]) -> bool:
            try:
                svg_plain = page_svg_text(page).replace(" ", "").replace("\n", "")
            except Exception:
                return False
            return compact in svg_plain

        await page.wait_for(_painted, timeout=10.0)
    await wait_for_visual_idle(page)
    return detail


def _patch_record_links(monkeypatch: pytest.MonkeyPatch) -> None:
    """Serve two link groups (outgoing + incoming, two relations) off-thread."""
    from sase.ace.tui.relations.link_index import LinkChip
    import sase.ace.tui.widgets.decks.record.relations as module

    chips = (
        LinkChip(
            relation="blocks",
            label="blocks",
            directed=True,
            this_is_source=True,
            neighbor_ref="@agent:downstream",
            neighbor_target=None,
            accent="#87D7FF",
            icon="•",
            why="",
            origin="manual",
            uses=0,
            created_by="",
            created_at="",
            writable=True,
        ),
        LinkChip(
            relation="relates-to",
            label="relates-to",
            directed=True,
            this_is_source=False,
            neighbor_ref="@agent:upstream",
            neighbor_target=None,
            accent="#87D7FF",
            icon="•",
            why="",
            origin="manual",
            uses=0,
            created_by="",
            created_at="",
            writable=True,
        ),
    )
    snapshot = SimpleNamespace(source_key=(("project", 1, 2),), errors=())
    monkeypatch.setattr(
        module, "load_artifact_links_snapshot", lambda _project: snapshot
    )
    monkeypatch.setattr(
        module,
        "link_index_for_snapshot",
        lambda _snapshot: SimpleNamespace(chips_for=lambda _reference: chips),
    )
    monkeypatch.setattr(
        module, "reference_for_agent_name", lambda name: f"agent:{name}"
    )


def _clear_record_cache() -> None:
    from sase.ace.tui.widgets.decks.record import loader as record_loader

    record_loader.clear_record_cache()


async def test_agents_record_inbox_lifecycle_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Record Lifecycle on an inbox agent: reference, location, status, times."""
    pin_visual_time(monkeypatch)
    pin_decks_paged(monkeypatch)
    _clear_record_cache()
    agent = make_agent(
        tmp_path,
        name="landed",
        suffix="record-lifecycle",
        status="DONE",
        summary=deck_summary("commit"),
    )
    patch_startup_loaders(monkeypatch, agents=[agent])
    async with AcePage(query='"visual"', patches=patches()) as page:
        await goto_agents(page, 1)
        detail = await show_record(page, preferred="lifecycle", expect="Lifecycle")
        assert detail.deck_area.panel(0).record_view.active_card_id == "lifecycle"
        assert_page_svg_contains(page, "Lifecycle")
        assert_page_svg_contains(page, "Inbox")
        assert_page_svg_contains(page, "@agent:landed")
        ace_png_visual.assert_page_png(
            page,
            "agents_record_inbox_lifecycle_120x40",
            title="ACE agents RECORD Lifecycle on inbox agent",
        )


async def test_agents_record_links_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Record Links on an agent with outgoing and incoming artifact links."""
    pin_visual_time(monkeypatch)
    pin_decks_paged(monkeypatch)
    _clear_record_cache()
    _patch_record_links(monkeypatch)
    agent = make_agent(
        tmp_path,
        name="linked",
        suffix="record-links",
        status="DONE",
        summary=deck_summary("commit"),
    )
    patch_startup_loaders(monkeypatch, agents=[agent])
    async with AcePage(query='"visual"', patches=patches()) as page:
        await goto_agents(page, 1)
        detail = await show_record(page, preferred="links", expect="Outgoing")
        assert detail.deck_area.panel(0).record_view.active_card_id == "links"
        assert_page_svg_contains(page, "Outgoing")
        assert_page_svg_contains(page, "Incoming")
        ace_png_visual.assert_page_png(
            page,
            "agents_record_links_120x40",
            title="ACE agents RECORD Links on agent with links",
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


def _wire(app: Any, corpus: ModelCorpus, *, rebuilding: bool = False) -> None:
    app._archive_get_corpus = lambda **kwargs: SimpleNamespace(
        corpus=corpus, profile=SimpleNamespace(digest="profile-1")
    )
    app._archive_probe_tokens = lambda: ArchiveRevalidationTokens(
        index_exists=True,
        index_stat=(1, 2),
        link_signature=(("proj", 1, 2),),
        profile_digest="profile-1",
        rebuilding=rebuilding,
        indexed_rows=41 if rebuilding else 0,
    )
    app._archive_load_facets = lambda: {}
    app._archive_profile = SimpleNamespace(digest="profile-1")
    app._archive_now = lambda: NOW


async def _wait_for_rows(page: AcePage) -> None:
    await page.wait_for(
        lambda _state: any(
            "@" in key
            for key in (
                page.app.query_one("#archive-list", ArchiveList).item_keys
                if page.app.query("#archive-list")
                else ()
            )
        ),
        timeout=15.0,
    )


async def _wait_for_svg(page: AcePage, needle: str, timeout: float = 15.0) -> None:
    """Poll decoded screen text until ``needle`` paints (spaces are plain)."""
    import asyncio

    start = asyncio.get_running_loop().time()
    while asyncio.get_running_loop().time() - start < timeout:
        if needle in page_svg_text(page):
            return
        await asyncio.sleep(0.1)  # sase-test-wait: poll SVG text paint
    raise AssertionError(f"timed out waiting for {needle!r} in the Archive view")


async def _open_archive(
    page: AcePage, rows: list[dict[str, Any]], *, rebuilding: bool = False
) -> None:
    _wire(page.app, ModelCorpus(rows), rebuilding=rebuilding)
    note_inbox_applied_for_archive(page.app, load_state=complete_load())
    open_agents_archive_view(page.app)
    await _wait_for_rows(page)
    await _settle_archive_detail(page)
    await wait_for_visual_idle(page)


async def _settle_archive_detail(page: AcePage) -> None:
    """Outlast the 150 ms detail debounce plus the hydration worker."""
    import asyncio

    await asyncio.sleep(1.0)  # sase-test-wait: detail debounce settle


def _write_reply_bundle(tmp_path: Path) -> str:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "raw_prompt.md").write_text(
        "the archived prompt reads back verbatim", encoding="utf-8"
    )
    response = artifacts / "response.md"
    response.write_text("the archived reply reads back verbatim", encoding="utf-8")
    agent = make_archive_agent(
        status="DONE",
        cl_name="archived",
        agent_name="archived-run",
        start_time=datetime(2026, 10, 10, 15, 0, 0),
    )
    agent.artifacts_dir = str(artifacts)
    agent.response_path = str(response)
    bundle = tmp_path / "bundles" / "r1.json"
    bundle.parent.mkdir(parents=True, exist_ok=True)
    bundle.write_text(json.dumps(agent.to_bundle_dict()), encoding="utf-8")
    return str(bundle)


async def test_agents_record_archived_lifecycle_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Record Lifecycle on a hydrated archived agent inside the amber Archive."""
    patch_startup_loaders(monkeypatch, agents=[_inbox_agent()])
    pin_agents_visual_now(monkeypatch, NOW)
    pin_decks_paged(monkeypatch)
    _clear_record_cache()
    bundle_path = _write_reply_bundle(tmp_path)
    rows = [
        light_row(
            "r1",
            day="2026-10-10",
            hour=15,
            name="archived-run",
            status="DONE",
            bundle_path=bundle_path,
        ),
        light_row("d02", day="2026-10-10", hour=12, name="today.other"),
    ]
    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        await _open_archive(page, rows)

        await _wait_for_svg(page, "ARCHIVED")
        detail = await show_record(page, preferred="lifecycle", expect="Time basis")
        assert detail.deck_area.panel(0).record_view.active_card_id == "lifecycle"
        assert_page_svg_contains(page, "Archive")
        assert_page_svg_contains(page, "@agent:archived-run")
        assert_page_svg_contains(page, "Outcome")
        assert_page_svg_contains(page, "Last activity")
        assert_page_svg_contains(page, "Time basis")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "agents_record_archived_lifecycle_120x40",
            title="ACE agents RECORD Lifecycle on archived agent",
        )


async def test_agents_record_unreadable_entry_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Record on an unreadable archive entry renders the light-row subject."""
    patch_startup_loaders(monkeypatch, agents=[_inbox_agent()])
    pin_agents_visual_now(monkeypatch, NOW)
    pin_decks_paged(monkeypatch)
    _clear_record_cache()
    rows = [
        light_row(
            "m01",
            day="2026-10-10",
            hour=15,
            name="missing.bundle",
            bundle_path="/nonexistent/archive-missing-bundle.json",
        ),
    ]
    async with AcePage(initial_tab="agents") as page:
        await wait_for_startup(page)
        await _open_archive(page, rows)

        await _wait_for_svg(page, "Record only")
        detail = await show_record(page, preferred="lifecycle", expect="Lifecycle")
        assert detail.deck_area.panel(0).record_view.active_card_id == "lifecycle"
        assert_page_svg_contains(page, "@agent:missing.bundle")
        assert_page_svg_contains(page, "missing.bundle")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "agents_record_unreadable_entry_120x40",
            title="ACE agents RECORD on unreadable archive entry",
        )
