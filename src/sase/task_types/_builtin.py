"""SASE's builtin declarative task-type specs.

Empty for now: the ``bug``/``ci``/``feature``/``flake``/``memory`` specs are
authored in a later phase (``sase bead task-type`` and its builtins). This
class exists so catalog assembly always has a builtin source to collect from,
exactly as :class:`sase.artifact_providers._builtin.BuiltinArtifactProviders`
does for artifact providers.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._hookspec import hookimpl


class BuiltinTaskTypes:
    """Builtin task types registered through the task-type host path."""

    @hookimpl
    def task_type_specs(self) -> tuple[Mapping[str, Any], ...]:
        return ()


__all__ = [
    "BuiltinTaskTypes",
]
