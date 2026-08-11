"""Shared helpers for the Wait modal test modules."""

from __future__ import annotations

from collections.abc import Callable

from textual.app import App, ComposeResult

from sase.ace.tui.models.wait_bead_catalog import WaitBeadCandidate, WaitBeadCatalog
from sase.ace.tui.modals.wait_modal import (
    WaitAgentCandidate,
    WaitModal,
    WaitModalResult,
)


class WaitModalTestApp(App[WaitModalResult | None]):
    """Minimal app harness for Wait modal tests."""

    def compose(self) -> ComposeResult:
        yield from ()


def candidate(
    wait_name: str,
    *,
    label: str | None = None,
    status: str = "RUNNING",
) -> WaitAgentCandidate:
    return WaitAgentCandidate(
        wait_name=wait_name,
        label=label or wait_name,
        status=status,
        model="claude / sonnet",
        start_time="12:03",
        duration="2m",
    )


def bead(
    bead_id: str,
    *,
    title: str = "Title",
    status: str = "open",
    updated_at: str = "2026-01-01T00:00:00Z",
) -> WaitBeadCandidate:
    return WaitBeadCandidate(
        bead_id=bead_id,
        title=title,
        status=status,
        type_label="task",
        created_at="2026-01-01T00:00:00Z",
        updated_at=updated_at,
    )


def bead_catalog(
    *candidates: WaitBeadCandidate,
    available: bool = True,
    closed_ids: frozenset[str] = frozenset(),
) -> WaitBeadCatalog:
    return WaitBeadCatalog(
        candidates=candidates, available=available, closed_ids=closed_ids
    )


def sync_loader(
    catalog: WaitBeadCatalog,
) -> Callable[..., WaitBeadCatalog]:
    def loader(
        project_key: str | None, *, own_bead_ids: frozenset[str] = frozenset()
    ) -> WaitBeadCatalog:
        return catalog

    return loader


async def await_bead_catalog(modal: WaitModal, pilot: object) -> None:
    worker = modal._bead_catalog_worker
    if worker is not None:
        await worker.wait()
    await pilot.pause()  # type: ignore[attr-defined]
