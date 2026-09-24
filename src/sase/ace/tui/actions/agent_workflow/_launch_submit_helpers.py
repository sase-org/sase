"""Shared helpers for ACE launch submission."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from pathlib import Path

from ...util.pump_tasks import spawn_pump_free_task
from ._launch_records import LaunchRecordContext
from ._types import PromptContext

log = logging.getLogger(__name__)


def submitted_vcs_xprompt_prefix(prompt: str) -> str | None:
    """Return ``#<workflow>:<ref>`` for *prompt*'s leading VCS tag, if any.

    Project tags (``+<project>``) resolve through the tag-aware helper.
    """
    from sase.project_tags import (
        effective_vcs_workflow_tag_with_catalog,
        peek_project_tag_catalog,
    )
    from sase.xprompt._parsing import extract_project_from_vcs_tag

    tag = effective_vcs_workflow_tag_with_catalog(
        prompt.strip() + " ", peek_project_tag_catalog()
    )
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
    """Refresh the Space MRU from the prompt actually submitted.

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
        log.debug("Failed to refresh Space replay target", exc_info=True)


def schedule_submit_time_vcs_replay(app: object, prompts: Sequence[str]) -> None:
    """Refresh the Space MRU for submitted *prompts* off the UI thread.

    Working out each prompt's VCS prefix can load the project-tag catalog and
    recording it writes the MRU file, so neither belongs in the submit handler
    that must return before the prompt bar's removal is painted.
    """

    def record_all() -> None:
        for prompt in prompts:
            record_submit_time_vcs_replay(prompt)

    async def record_off_thread() -> None:
        await asyncio.to_thread(record_all)

    task = spawn_pump_free_task(
        app,
        record_off_thread(),
        name="launch-vcs-replay",
        registry_attr="_launch_vcs_replay_tasks",
    )
    if task is None:
        # No running event loop means no UI to keep responsive.
        record_all()


def dispatch_payload_from_prompt_context(ctx: PromptContext) -> dict[str, object]:
    """Return launch payload fields that identify portable dispatch source."""
    project_name = Path(ctx.project_file).expanduser().parent.name or ctx.project_name
    payload: dict[str, object] = {
        "display_name": ctx.display_name,
        "project_name": ctx.project_name,
        "workflow_name": ctx.workflow_name,
        "project": project_name,
    }
    if ctx.cl_name and ctx.cl_name != project_name:
        payload["patch_ref"] = ctx.cl_name
    return payload


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
    "schedule_submit_time_vcs_replay",
    "submitted_vcs_xprompt_prefix",
    "vcs_workflow_type_from_tag",
]
