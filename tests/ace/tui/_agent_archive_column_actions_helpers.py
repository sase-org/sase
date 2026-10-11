"""Shared setup helpers for archive column action tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agents._archive_view import open_agents_archive_view
from tests.ace.tui._agent_archive_column_helpers import ColumnHarness, light_row


def history_rows() -> list[dict[str, Any]]:
    """120 runs: 40 today, 40 yesterday, 40 on a day two weeks back."""
    rows: list[dict[str, Any]] = []
    for day, tag in (("2026-10-10", "t"), ("2026-10-09", "y"), ("2026-09-26", "w")):
        for index in range(40):
            rows.append(light_row(f"{tag}{index:02d}", day=day, hour=23 - (index % 20)))
    return rows


async def opened(
    rows: list[dict[str, Any]] | None = None, **kwargs: Any
) -> ColumnHarness:
    harness = ColumnHarness(rows if rows is not None else history_rows(), **kwargs)
    harness.note_inbox_applied()
    open_agents_archive_view(harness.owner)
    await harness.settle()
    return harness


def selection_key(harness: ColumnHarness) -> str | None:
    return harness.archive.selected_key


def clan_rows() -> list[dict[str, Any]]:
    clan = "clan:swarm:1"
    return [
        light_row("m1", hour=22, name="swarm.one", container_key=clan),
        light_row("m2", hour=21, name="swarm.two", container_key=clan),
        light_row("m3", hour=20, name="swarm.three", container_key=clan),
        light_row("solo", hour=19, name="loner"),
    ]
