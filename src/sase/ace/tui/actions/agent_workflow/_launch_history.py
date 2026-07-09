"""Launch history and replay helpers for agent workflow actions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

from ._types import PromptContext

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sase.ace.tui.modals import SelectionItem


class _ReplaySelectionHost(Protocol):
    _last_custom_agent_selection: SelectionItem | None


class _VcsPromptResolver(Protocol):
    def __call__(
        self,
        prompt: str,
        workflow_type: str,
        *,
        skip_workspace: bool = False,
    ) -> tuple[str, str, str, int, str] | None: ...


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
    record_launched_vcs_xprompt_usage(vcs_ref, project_name=project_name)


def record_launched_vcs_xprompt_usage(
    vcs_ref: tuple[str, str],
    *,
    project_name: str | None = None,
    prompt: str | None = None,
    resolve_vcs_from_prompt: _VcsPromptResolver | None = None,
) -> None:
    """Record the VCS MRU prefix for a submitted launch path.

    Workspace workflows need the owning project name for the launchability
    guard. Paths that only detected a raw ref can provide the submitted prompt
    and resolver; resolution is run with workspace allocation skipped.
    """
    workflow_type, ref = vcs_ref
    prefix = f"#{workflow_type}:{ref}"

    from sase.history.vcs_xprompt_mru import (
        is_default_vcs_xprompt_prefix,
        record_vcs_xprompt_usage,
    )

    owner_project_name = project_name
    if prompt is not None and resolve_vcs_from_prompt is not None:
        try:
            resolved = resolve_vcs_from_prompt(
                prompt,
                workflow_type,
                skip_workspace=True,
            )
        except Exception:
            log.debug("Failed to resolve VCS MRU owner for %r", prefix, exc_info=True)
        else:
            if resolved is not None:
                owner_project_name = resolved[1]
                ref = resolved[4]
                prefix = f"#{workflow_type}:{ref}"

    if is_default_vcs_xprompt_prefix(prefix):
        record_vcs_xprompt_usage(prefix)
        return

    if owner_project_name is None:
        return
    if not _is_launchable_replay_project(owner_project_name):
        return

    record_vcs_xprompt_usage(prefix)


def save_replayable_vcs_selection(
    app: _ReplaySelectionHost,
    ctx: PromptContext,
    vcs_ref: tuple[str, str],
) -> None:
    """Persist the repeat-last selection only for launchable project owners.

    The implicit default ``#git:home`` (used to normalize bare home-mode
    launches) is never persisted: it is normalized data, not a user-selected
    VCS workflow, so it must not become the target of ``Ctrl+Space``. This
    covers both a bare prompt that was normalized and an explicit ``#git:home``
    prompt, which both resolve to ``("git", "home")``.
    """
    from sase.history.vcs_xprompt_mru import is_default_vcs_xprompt_prefix

    workflow_type, _ref = vcs_ref
    if is_default_vcs_xprompt_prefix(f"#{workflow_type}:{_ref}"):
        return

    from ...modals import SelectionItem
    from sase.ace.last_agent_selection import save_last_agent_selection_if_launchable

    if _ref == ctx.project_name:
        sel = SelectionItem(
            display_name=f"[P] {ctx.project_name}",
            item_type="project",
            project_name=ctx.project_name,
            cl_name=None,
        )
    else:
        sel = SelectionItem(
            display_name=f"[PR] {_ref}",
            item_type="cl",
            project_name=ctx.project_name,
            cl_name=_ref,
        )
    if save_last_agent_selection_if_launchable(sel):
        app._last_custom_agent_selection = sel
