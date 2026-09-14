"""Worker-thread disk IO helpers for agent loading."""

from __future__ import annotations

import sys
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from . import _loading_helpers

if TYPE_CHECKING:
    from ...models.agent import AgentType
    from sase.current_project import CurrentProject


def resolve_load_agents_from_disk_with_state() -> Callable[..., Any]:
    """Resolve through the public facade so existing monkeypatches still work."""
    facade = sys.modules.get(f"{__package__}._loading")
    loader = getattr(
        facade,
        "load_agents_from_disk_with_state",
        _loading_helpers.load_agents_from_disk_with_state,
    )
    return cast(Callable[..., Any], loader)


def disk_load_with_optional_current_project(
    dismissed_snapshot: set[tuple[AgentType, str, str | None]],
    *,
    resolve_current: bool,
    **load_kwargs: Any,
) -> tuple[Any, CurrentProject | None]:
    """Load agents and, when requested, resolve the current project.

    Both reads belong on a worker thread: ``resolve_current_project``
    parses the MRU JSON plus project records and the Patch cache.
    """
    load_result = resolve_load_agents_from_disk_with_state()(
        dismissed_snapshot,
        **load_kwargs,
    )
    current: CurrentProject | None = None
    if resolve_current:
        from sase.current_project import resolve_current_project

        current = resolve_current_project()
    return load_result, current
