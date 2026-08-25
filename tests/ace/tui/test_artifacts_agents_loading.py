"""Two-stage loading coverage for the Artifacts Agent pane."""

from __future__ import annotations

from threading import Event

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts import agents_pane
from sase.ace.tui.widgets.artifacts.agents_data import (
    AGENTS_FIRST_PAGE_LIMIT,
    AgentsSnapshot,
)
from sase.ace.tui.widgets.artifacts.agents_pane import ArtifactsAgentsPane
from tests._agent_catalog_helpers import make_agent_catalog_row
from tests._load_tolerant import LOAD_TOLERANT_TIMEOUT


async def test_agent_first_page_paints_before_full_extension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_rows = (
        make_agent_catalog_row("newest", started_at="2026-08-24T12:00:00+00:00"),
        make_agent_catalog_row("older", started_at="2026-08-24T11:00:00+00:00"),
    )
    full_rows = (
        *first_rows,
        make_agent_catalog_row("oldest", started_at="2026-08-24T10:00:00+00:00"),
    )
    full_started = Event()
    release_full = Event()
    requested_limits: list[int | None] = []
    indexed_row_counts: list[int] = []

    def load(project: str | None, limit: int | None = None) -> AgentsSnapshot:
        requested_limits.append(limit)
        if limit is None:
            full_started.set()
            assert release_full.wait(timeout=LOAD_TOLERANT_TIMEOUT)
            return AgentsSnapshot(
                project=project,
                rows=full_rows,
                total_row_count=len(full_rows),
                complete=True,
            )
        return AgentsSnapshot(
            project=project,
            rows=first_rows,
            total_row_count=len(full_rows),
            complete=False,
        )

    original_build = ArtifactsAgentsPane._build_agents_query_index

    def build_index(
        self: ArtifactsAgentsPane, snapshot: AgentsSnapshot, *, generation: int
    ):
        indexed_row_counts.append(len(snapshot.rows))
        return original_build(self, snapshot, generation=generation)

    monkeypatch.setattr(agents_pane, "load_agents_snapshot", load)
    monkeypatch.setattr(ArtifactsAgentsPane, "_build_agents_query_index", build_index)

    try:
        async with AcePage(initial_tab="patches", startup_policy="real") as page:
            await page.press(page.artifacts_digit("agents"))
            pane = page.query_one_widget(
                "#artifacts-agents-pane",
                ArtifactsAgentsPane,
            )
            await page.wait_for(
                lambda _state: (
                    pane.snapshot is not None and len(pane.snapshot.rows) == 2
                ),
                timeout=LOAD_TOLERANT_TIMEOUT,
            )

            assert pane.snapshot is not None
            assert pane.snapshot.complete is False
            assert pane._query_index is None
            assert requested_limits[0] == AGENTS_FIRST_PAGE_LIMIT
            assert indexed_row_counts == []

            pane._commit_agents_query("role:code limit:100")
            _filtered, exact, pending, _truncated, match_count = (
                pane._filtered_agents_snapshot()
            )
            assert exact is False
            assert pending is True
            assert match_count is None

            assert full_started.wait(timeout=LOAD_TOLERANT_TIMEOUT)
            assert requested_limits[:2] == [AGENTS_FIRST_PAGE_LIMIT, None]

            release_full.set()
            await page.wait_for(
                lambda _state: (
                    pane.snapshot is not None
                    and pane.snapshot.complete
                    and len(pane.snapshot.rows) == 3
                    and pane._query_index is not None
                ),
                timeout=LOAD_TOLERANT_TIMEOUT,
            )
            assert indexed_row_counts == [len(full_rows)]
    finally:
        release_full.set()
