"""Shared Agents Archive PNG snapshot fixtures and navigation helpers.

Public helpers for the ``test_ace_png_snapshots_agents_archive*`` split. This
module is private (``_``-prefixed); the helpers are public so each split test
module can import them without importing a ``_``-prefixed name across modules.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from sase.ace.testing import AcePage
from sase.ace.tui.actions.agents._archive_column import archive_container_members
from sase.ace.tui.actions.agents._archive_controller import (
    note_inbox_applied_for_archive,
)
from sase.ace.tui.actions.agents._archive_view import (
    archive_detail_owns_panel,
    get_agents_tab_selection,
)
from sase.ace.tui.actions.agents._archive_view import open_agents_archive_view
from sase.ace.tui.models.agent_archive_view import (
    ARCHIVE_ROW_AGENT,
    ARCHIVE_ROW_CONTAINER,
    container_key_of,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_archive_controller import ArchiveRevalidationTokens
from sase.ace.tui.widgets.agents_archive import ArchiveList
from tests.ace.tui._agent_archive_column_helpers import (
    ModelCorpus,
    complete_load,
    light_row,
)
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import page_svg_text
from tests.ace.tui.visual._ace_png_snapshot_helpers import wait_for_visual_idle

NOW = datetime(2026, 10, 10, 20, 0, tzinfo=UTC)


def inbox_agent() -> Agent:
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


def wire(app: Any, corpus: ModelCorpus, *, rebuilding: bool = False) -> None:
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


def list_history() -> list[dict[str, Any]]:
    rows = [
        light_row("d01", day="2026-10-10", hour=18, name="today.done"),
        light_row(
            "d02",
            day="2026-10-10",
            hour=17,
            name="today.failed",
            outcome="failed",
            status="FAILED",
        ),
        light_row(
            "d03",
            day="2026-10-10",
            hour=16,
            name="today.running",
            status="RUNNING",
            stop_time=None,
            time_basis="started",
            outcome="interrupted",
        ),
    ]
    rows += [
        light_row(
            "c1",
            day="2026-10-09",
            hour=15,
            name="clan.alpha",
            container_key="archive:u.m@clan1",
        ),
        light_row(
            "c2",
            day="2026-10-09",
            hour=14,
            name="clan.beta",
            container_key="archive:u.m@clan1",
        ),
    ]
    rows += [light_row("o01", day="2026-09-20", hour=12, name="old.solo")]
    return rows


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


async def wait_for_svg(page: AcePage, needle: str, timeout: float = 15.0) -> None:
    """Poll decoded screen text until ``needle`` paints (spaces are plain)."""
    start = asyncio.get_running_loop().time()
    while asyncio.get_running_loop().time() - start < timeout:
        if needle in page_svg_text(page):
            return
        await asyncio.sleep(0.1)  # sase-test-wait: poll SVG text paint
    raise AssertionError(f"timed out waiting for {needle!r} in the Archive view")


async def open_archive(
    page: AcePage, rows: list[dict[str, Any]], *, rebuilding: bool = False
) -> None:
    wire(page.app, ModelCorpus(rows), rebuilding=rebuilding)
    note_inbox_applied_for_archive(page.app, load_state=complete_load())
    open_agents_archive_view(page.app)
    await _wait_for_rows(page)
    await settle_archive_detail(page)
    await wait_for_visual_idle(page)


async def settle_archive_detail(page: AcePage) -> None:
    """Wait for the current selection's detail paint and hydration to finish."""
    owner = page.app
    if not archive_detail_owns_panel(owner):
        await wait_for_visual_idle(page)
        return

    selection = get_agents_tab_selection(owner)
    key = selection.archive_key
    row_kind = selection.row_kind
    generation = owner._agents_archive_view.generation

    def settled() -> bool:
        if not archive_detail_owns_panel(owner):
            return False
        current = get_agents_tab_selection(owner)
        runtime = getattr(owner, "_archive_reader_runtime", None)
        if (
            current.archive_key != key
            or current.row_kind != row_kind
            or runtime is None
            or runtime.archive_key != key
            or runtime.generation != generation
            or runtime.loading
        ):
            return False
        if row_kind == ARCHIVE_ROW_CONTAINER:
            container_key = container_key_of(key)
            if container_key is None:
                return False
            members = archive_container_members(owner, container_key)
            names = tuple(str(member.get("agent_name", "")) for member in members)
            text = page_svg_text(page)
            return f"{len(members)} matching member(s)" in text and all(
                name in text for name in names
            )
        if row_kind == ARCHIVE_ROW_AGENT:
            return runtime.hydrated_agent is not None or runtime.unreadable
        return True

    await page.wait_for(
        lambda _state: settled(),
        timeout=15.0,
        timeout_message=lambda: (
            "Archive detail did not settle: "
            f"selection={get_agents_tab_selection(owner)!r}; "
            f"runtime={getattr(owner, '_archive_reader_runtime', None)!r}; "
            f"generation={generation}; visible={page_svg_text(page)!r}"
        ),
    )
    await wait_for_visual_idle(page)
