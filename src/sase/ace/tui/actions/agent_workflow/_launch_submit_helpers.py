"""Shared helpers for ACE launch submission."""

from __future__ import annotations

import logging
from pathlib import Path

from ._launch_records import LaunchRecordContext
from ._types import PromptContext

log = logging.getLogger(__name__)


def submitted_vcs_xprompt_prefix(prompt: str) -> str | None:
    """Return ``#<workflow>:<ref>`` for *prompt*'s leading VCS tag, if any."""
    from sase.xprompt._parsing import (
        extract_project_from_vcs_tag,
        extract_vcs_workflow_tag,
    )

    tag = extract_vcs_workflow_tag(prompt.strip() + " ")
    if tag is None:
        return None
    ref = extract_project_from_vcs_tag(tag)
    if not ref:
        return None
    workflow_type = vcs_workflow_type_from_tag(tag)
    if not workflow_type:
        return None
    return f"#{workflow_type}:{ref}"


def vcs_workflow_type_from_tag(tag: str) -> str | None:
    """Return the workflow-type prefix (e.g. ``"gh"``) of a leading VCS tag."""
    body = tag.strip()
    if not body.startswith("#"):
        return None
    body = body[1:]
    for suffix in ("!!", "??"):
        idx = body.find(suffix)
        if idx != -1:
            body = body[:idx] + body[idx + len(suffix) :]
            break
    for sep in ("(", ":", "_", "+"):
        idx = body.find(sep)
        if idx != -1:
            return body[:idx] or None
    return body or None


def launch_toast_label(prompt: str, fallback: str) -> str:
    """Return the launch-toast label for *prompt*.

    The prompt bar's ``ctx`` is baked when the bar opens; cycling the bar text
    with ``<ctrl+p>`` to a different VCS ref only mutates the text, never the
    context. Deriving the label from the submitted text keeps the "Launching
    agent for ..." toast honest about the cycled-to ref instead of the stale
    baked ``ctx.display_name``. Falls back to *fallback* when the prompt has no
    recognized leading VCS tag.
    """
    from sase.xprompt._parsing import extract_project_from_vcs_tag

    prefix = submitted_vcs_xprompt_prefix(prompt)
    if prefix is None:
        return fallback
    return extract_project_from_vcs_tag(prefix) or fallback


def record_submit_time_vcs_replay(prompt: str) -> None:
    """Refresh the Ctrl+Space MRU from the prompt actually submitted.

    ``record_vcs_xprompt_usage`` already drops the implicit ``#git:home``
    default and known non-launchable projects, so this is safe to call for
    every ACE submit including home-mode and bulk fan-out.
    """
    prefix = submitted_vcs_xprompt_prefix(prompt)
    if prefix is None:
        return
    try:
        from sase.history.vcs_xprompt_mru import record_vcs_xprompt_usage

        record_vcs_xprompt_usage(prefix)
    except Exception:
        log.debug("Failed to refresh Ctrl+Space replay target", exc_info=True)


def launch_record_context_from_prompt_context(
    ctx: PromptContext,
) -> LaunchRecordContext:
    project_name = Path(ctx.project_file).expanduser().parent.name
    cl_name = ctx.cl_name or (project_name if not ctx.is_home_mode else "")
    if not cl_name:
        cl_name = ctx.history_sort_key or ctx.display_name
    return launch_record_context(
        display_name=ctx.display_name,
        project_file=ctx.project_file,
        cl_name=cl_name,
        is_project_agent=not ctx.is_home_mode and cl_name == project_name,
    )


def launch_record_context(
    *,
    display_name: str,
    project_file: str,
    cl_name: str,
    is_project_agent: bool | None = None,
) -> LaunchRecordContext:
    project_name = Path(project_file).expanduser().parent.name
    resolved_cl_name = cl_name or project_name or display_name
    return LaunchRecordContext(
        display_name=display_name,
        project_file=project_file,
        cl_name=resolved_cl_name,
        is_project_agent=(
            resolved_cl_name == project_name
            if is_project_agent is None
            else is_project_agent
        ),
    )


__all__ = [
    "launch_record_context",
    "launch_record_context_from_prompt_context",
    "launch_toast_label",
    "record_submit_time_vcs_replay",
    "submitted_vcs_xprompt_prefix",
    "vcs_workflow_type_from_tag",
]
