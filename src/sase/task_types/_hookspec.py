"""Pluggy hook specification for task-type plugins."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pluggy

hookspec = pluggy.HookspecMarker("sase_task_type")
hookimpl = pluggy.HookimplMarker("sase_task_type")


class TaskTypeHookSpec:
    """Hook specification for declarative task-type specs."""

    @hookspec
    def task_type_specs(
        self,
    ) -> Iterable[Mapping[str, Any]] | Mapping[str, Any] | None:
        """Return declarative task-type specs (see ``TaskTypeSpecWire``)."""
        ...


__all__ = [
    "TaskTypeHookSpec",
    "hookimpl",
    "hookspec",
]
