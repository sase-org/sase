"""Shared app-owned context accessors for agent detail rendering."""

from __future__ import annotations

from ...models.agent_runner_slots import RunnerCapacitySnapshot


def runner_capacity_for_app(app: object | None) -> RunnerCapacitySnapshot | None:
    """Return the current immutable runner snapshot owned by *app*."""
    capacity = getattr(app, "_agent_runner_capacity", None)
    return capacity if isinstance(capacity, RunnerCapacitySnapshot) else None
