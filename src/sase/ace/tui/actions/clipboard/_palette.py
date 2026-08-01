"""Warm-only context construction for the ACE Copy as palette."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.project_display_names import humanize_cl_name

from ...commands import CommandContext
from ._palette_artifacts import build_artifacts_context
from ._palette_helpers import (
    axe_item_label,
    notify_copy_warning,
    number_from_url,
    output_hint,
    shorten,
    warm_agent_file_path,
)
from ._palette_registry import (
    _DISPATCH_ORDER as _DISPATCH_ORDER,
    context_from_registry,
)

if TYPE_CHECKING:
    from ...modals.copy_as_types import CopyAsContext


_ARTIFACT_SUBTABS = frozenset({"commits", "beads", "plans", "chats", "bugs", "other"})


def build_copy_as_context(app: Any) -> CopyAsContext | None:
    """Capture a palette context without filesystem or subprocess work."""

    tab = app.current_tab
    subtab = getattr(app, "current_artifacts_pane_key", "prs")
    if tab == "changespecs" and subtab in _ARTIFACT_SUBTABS:
        return build_artifacts_context(app, subtab)
    if tab == "changespecs":
        return _build_changespec_context(app)
    if tab == "agents":
        return _build_agent_context(app)
    return _build_axe_context(app)


def _build_changespec_context(app: Any) -> CopyAsContext | None:
    changespecs = getattr(app, "changespecs", ())
    index = getattr(app, "current_idx", 0)
    changespec = changespecs[index] if 0 <= index < len(changespecs) else None
    if changespec is None:
        notify_copy_warning(app, "No ChangeSpec to copy")
        return None

    ctx = CommandContext(
        tab="changespecs",
        artifacts_subtab="prs",
        changespec=changespec,
    )
    previews = {
        "raw": shorten(
            getattr(changespec, "description", "")
            or f"{changespec.status} · {humanize_cl_name(changespec.name)}"
        ),
        "with_snapshot": "ChangeSpec + current pane",
        "bug": shorten(getattr(changespec, "bug", "")),
        "pr_number": number_from_url(getattr(changespec, "pr_url", None)),
        "name": humanize_cl_name(changespec.name),
        "link": shorten(getattr(changespec, "pr_url", "") or ""),
        "spec": shorten(getattr(changespec, "file_path", "")),
        "snapshot": "current pane",
    }
    project = (
        getattr(changespec, "project_display_name", None)
        or getattr(changespec, "project_query_name", None)
        or "ChangeSpecs"
    )
    subtitle = f"{project} · {humanize_cl_name(changespec.name)}"
    return context_from_registry(
        app,
        group="changespecs",
        command_context=ctx,
        subtitle=subtitle,
        unknown_context="ChangeSpecs",
        previews=previews,
    )


def _build_agent_context(app: Any) -> CopyAsContext | None:
    resolver = getattr(app, "_get_selected_agent", None)
    try:
        agent = resolver() if callable(resolver) else None
    except Exception:
        agent = None
    if agent is None:
        notify_copy_warning(app, "No agent selected")
        return None

    file_path = warm_agent_file_path(app)
    ctx = CommandContext(
        tab="agents",
        agent=agent,
        file_panel_visible=file_path is not None,
    )
    presented_name = (
        getattr(agent, "presented_agent_name", None)
        or getattr(agent, "display_name", None)
        or getattr(agent, "cl_name", "agent")
    )
    project = getattr(agent, "project_display_name", None)
    subtitle = f"{project} · {presented_name}" if project else str(presented_name)
    response_path = getattr(agent, "response_path", None)
    status = str(getattr(agent, "status", "")).lower()
    previews = {
        "chat": shorten(response_path or ""),
        "file_path": shorten(file_path or ""),
        "name": shorten(str(presented_name)),
        "prompt": f"{status} agent prompt" if status else "agent prompt",
        "reference": (
            f"@agent:{getattr(agent, 'agent_name', '')}"
            if getattr(agent, "agent_name", None)
            else ""
        ),
        "snapshot": "current pane",
    }
    return context_from_registry(
        app,
        group="agents",
        command_context=ctx,
        subtitle=subtitle,
        unknown_context="agents",
        previews=previews,
    )


def _build_axe_context(app: Any) -> CopyAsContext | None:
    items = getattr(app, "_axe_items", ())
    index = getattr(app, "current_idx", 0)
    item = items[index] if 0 <= index < len(items) else None
    if item is None:
        notify_copy_warning(app, "No AXE item to copy")
        return None

    ctx = CommandContext(tab="axe", axe_item=item)
    subtitle = axe_item_label(item)
    output = getattr(app, "_axe_output", "")
    output_preview = output_hint(output)
    if getattr(app, "_axe_current_view", "axe") != "axe":
        output_preview = (
            f"command output · {output_preview}" if output_preview else "command output"
        )
    previews = {
        "visible": output_preview or "visible output",
        "full": output_preview or "full output",
        "snapshot": "current pane",
    }
    return context_from_registry(
        app,
        group="axe",
        command_context=ctx,
        subtitle=subtitle,
        unknown_context="axe",
        previews=previews,
    )


__all__ = ["build_copy_as_context"]
