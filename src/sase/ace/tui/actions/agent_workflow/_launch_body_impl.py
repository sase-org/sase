"""Worker-thread launch body orchestration for agent workflow actions."""

from __future__ import annotations

import logging
from typing import Any

from ._launch_body_single import run_single_agent_launch_body
from ._launch_history import (
    record_launched_vcs_xprompt_usage,
    record_prompt_file_references,
)
from ._launch_tasks import LaunchTaskOutcome
from ._types import PromptContext
from ..failure_messages import with_log_panel_hint

log = logging.getLogger(__name__)


def run_agent_launch_body(
    app: Any, prompt: str, ctx: PromptContext | None = None
) -> LaunchTaskOutcome:
    """Run the blocking body for a single submitted prompt."""
    owns_context = ctx is None
    if ctx is None:
        ctx = app._prompt_context
    if ctx is None:
        # Context was cleared between the submit and the worker tick
        # (e.g. another launch path ran); nothing to do.
        return LaunchTaskOutcome(
            "Launch skipped: prompt context is no longer available",
            severity="warning",
        )
    original_submitted_prompt = prompt
    from sase.xprompt.unresolved import (
        format_unresolved_references_toast,
        scan_query_for_unresolved_references,
    )

    unresolved_refs = scan_query_for_unresolved_references(prompt)
    unresolved_warning_messages = (
        (format_unresolved_references_toast(unresolved_refs),)
        if unresolved_refs
        else ()
    )

    def _with_unresolved_warnings(
        outcome: LaunchTaskOutcome,
    ) -> LaunchTaskOutcome:
        return outcome.with_warning_messages(unresolved_warning_messages)

    from sase.agent.launch_validation import (
        force_reuse_owner_names,
        rewrite_force_reuse_name_directives,
        wipe_names_for_forced_reuse,
    )

    force_reuse_names = force_reuse_owner_names([prompt])
    if force_reuse_names:
        try:
            wipe_names_for_forced_reuse(force_reuse_names)
        except Exception as exc:
            log.exception("Forced agent-name reuse wipe failed")
            from sase.history.prompt import record_failed_launch_prompt
            from sase.logs import log_launch_failure

            record_failed_launch_prompt(original_submitted_prompt)
            log_launch_failure(
                kind="single",
                display_name=ctx.display_name,
                exc=exc,
                project=ctx.project_name,
                workspace_num=ctx.workspace_num,
                prompt_preview=original_submitted_prompt,
                stage="force_reuse_wipe",
            )
            if owns_context:
                app._prompt_context = None
            return _with_unresolved_warnings(
                LaunchTaskOutcome(
                    with_log_panel_hint("Agent name reuse failed"),
                    severity="error",
                )
            )
        prompt = rewrite_force_reuse_name_directives(prompt)

    from sase.project_aliases import canonicalize_project_aliases_in_prompt

    prompt = canonicalize_project_aliases_in_prompt(prompt)
    submitted_xprompt = prompt
    from sase.agent.launch_timing import LaunchTimingRecorder
    from sase.agent.names import ensure_historical_auto_name_migration

    ensure_historical_auto_name_migration()

    timer = LaunchTimingRecorder(
        "tui_agent_launch",
        {
            "prompt_len": len(prompt),
            "project_name": ctx.project_name,
            "home_mode": ctx.is_home_mode,
        },
        durable=True,
    )

    # Check if this is a bulk run.
    if app._bulk_changespecs:
        from sase.agent.multi_prompt import is_multi_prompt

        if is_multi_prompt(prompt):
            from sase.history.prompt import record_failed_launch_prompt

            record_failed_launch_prompt(prompt)
            app._bulk_changespecs = None
            if owns_context:
                app._prompt_context = None
            return _with_unresolved_warnings(
                LaunchTaskOutcome(
                    "Multi-prompt is not supported with bulk launch",
                    severity="error",
                )
            )
        # These dispatchers are synchronous optimistic/task-queue staging
        # callbacks; the launched work itself never runs on the app pump.
        app.call_later(app._launch_bulk_agents, prompt)
        return _with_unresolved_warnings(
            LaunchTaskOutcome("Bulk launch queued", notify=False)
        )

    from sase.workspace_provider import get_ref_patterns
    from sase.xprompt._parsing import normalize_default_vcs_workflow_segment

    # Detect xprompt swarms before injecting the default workspace
    # ref; an xprompt swarm must still look like the sole top-level
    # reference in its segment.
    from sase.agent.xprompt_swarm import (
        expand_xprompt_swarms_with_metadata,
    )
    from sase.agent.multi_prompt import parse_multi_prompt

    with timer.stage("prompt_parse"):
        multi = parse_multi_prompt(prompt)
        from sase.agent.launch_projects import (
            enable_known_project_vcs_refs_for_launch_prompt,
        )

        enable_known_project_vcs_refs_for_launch_prompt("\n---\n".join(multi.segments))
    with timer.stage("xprompt_swarm_expand", segment_count=len(multi.segments)):
        expanded_records = expand_xprompt_swarms_with_metadata(
            multi.segments, multi.local_xprompts
        )
        multi.segments = [record.prompt for record in expanded_records]
        multi.template_groups = [record.template_group for record in expanded_records]
    if len(multi.segments) > 1:
        if ctx.is_home_mode:
            multi.segments = [
                normalize_default_vcs_workflow_segment(segment)
                for segment in multi.segments
            ]
        normalized_prompt = "\n---\n".join(multi.segments)
        _vcs_prompt = normalized_prompt
        with timer.stage("vcs_resolution", launch_kind="multi_prompt"):
            try:
                from sase.axe.run_agent_phases import resolve_agent_refs_in_prompt

                _vcs_prompt, _ = resolve_agent_refs_in_prompt(normalized_prompt)
            except Exception:
                pass  # Agent not found - runner will resolve later

            mp_vcs_ref: tuple[str, str] | None = None
            ref_patterns = get_ref_patterns()
            for wf_name, pattern in ref_patterns.items():
                match = pattern.search(_vcs_prompt)
                if match is not None:
                    ref_value = match.group(1) or match.group(2)
                    if ref_value:
                        mp_vcs_ref = (wf_name, ref_value)
                        ctx.display_name = ref_value
                        ctx.history_sort_key = ref_value
                        break
        from sase.history.prompt import (
            add_or_update_prompt,
            record_failed_launch_prompt,
        )

        with timer.stage("history_write", launch_kind="multi_prompt"):
            try:
                from sase.agent.launch_validation import validate_launch_name_requests

                validate_launch_name_requests(multi.segments)
            except RuntimeError as exc:
                err_msg = str(exc)
                record_failed_launch_prompt(submitted_xprompt)
                if owns_context:
                    app._prompt_context = None
                timer.finish(dispatch="multi_prompt", outcome="cancelled")
                return _with_unresolved_warnings(
                    LaunchTaskOutcome(err_msg, severity="error")
                )
            add_or_update_prompt(
                submitted_xprompt,
                allow_short=True,
            )
            record_prompt_file_references(submitted_xprompt)
        if mp_vcs_ref is not None:
            record_launched_vcs_xprompt_usage(
                mp_vcs_ref,
                prompt=_vcs_prompt,
                resolve_vcs_from_prompt=app._resolve_vcs_from_prompt,
            )
        if owns_context:
            app._prompt_context = None
        timer.finish(dispatch="multi_prompt", segment_count=len(multi.segments))
        # Synchronous task-queue staging; preserves post-validation ordering.
        app.call_later(
            app._launch_multi_prompt_agents,
            multi,
            ctx,
            mp_vcs_ref,
            submitted_xprompt,
        )
        return _with_unresolved_warnings(
            LaunchTaskOutcome(
                f"Multi-prompt launch queued for {ctx.display_name}",
                notify=False,
            )
        )

    return run_single_agent_launch_body(
        app,
        prompt=prompt,
        ctx=ctx,
        owns_context=owns_context,
        original_submitted_prompt=original_submitted_prompt,
        submitted_xprompt=submitted_xprompt,
        unresolved_warning_messages=unresolved_warning_messages,
        timer=timer,
    )
