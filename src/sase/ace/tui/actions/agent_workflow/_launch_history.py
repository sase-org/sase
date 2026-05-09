"""Launch history and replay helpers for agent workflow actions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from ._ref_resolution import is_non_workspace_workflow
from ._types import PromptContext

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sase.ace.tui.modals import SelectionItem


class _ReplaySelectionHost(Protocol):
    _last_custom_agent_selection: SelectionItem | None


def record_prompt_file_references(prompt: str) -> None:
    """Extract and record file references from *prompt* into history."""
    from sase.history.file_references import (
        extract_recordable_file_refs,
        record_file_references,
    )

    refs = extract_recordable_file_refs(prompt)
    if refs:
        record_file_references(refs)


def _is_launchable_replay_project(project_name: str) -> bool:
    from sase.ace.tui.modals.project_discovery import is_launchable_project

    try:
        return is_launchable_project(project_name)
    except Exception:
        log.exception("Failed to validate replay project %r", project_name)
        return False


def record_resolved_vcs_xprompt_usage(
    vcs_ref: tuple[str, str],
    project_name: str,
) -> None:
    """Record a VCS MRU prefix only after resolution proves it is reusable."""
    workflow_type, ref = vcs_ref
    if not is_non_workspace_workflow(
        workflow_type
    ) and not _is_launchable_replay_project(project_name):
        return

    from sase.history.vcs_xprompt_mru import record_vcs_xprompt_usage

    record_vcs_xprompt_usage(f"#{workflow_type}:{ref}")


def save_replayable_vcs_selection(
    app: _ReplaySelectionHost,
    ctx: PromptContext,
    vcs_ref: tuple[str, str],
) -> None:
    """Persist the repeat-last selection only for launchable project owners."""
    from ...modals import SelectionItem
    from sase.ace.last_agent_selection import save_last_agent_selection_if_launchable

    _ref = vcs_ref[1]
    if _ref == ctx.project_name:
        sel = SelectionItem(
            display_name=f"[P] {ctx.project_name}",
            item_type="project",
            project_name=ctx.project_name,
            cl_name=None,
        )
    else:
        sel = SelectionItem(
            display_name=f"[C] {_ref}",
            item_type="cl",
            project_name=ctx.project_name,
            cl_name=_ref,
        )
    if save_last_agent_selection_if_launchable(sel):
        app._last_custom_agent_selection = sel
