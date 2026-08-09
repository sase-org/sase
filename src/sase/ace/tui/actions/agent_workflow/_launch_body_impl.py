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
        force_reuse_bead_associations_by_prompt,
        force_reuse_owner_names,
        preflight_launch_name_requests,
        rewrite_force_reuse_name_directives,
        wipe_names_for_forced_reuse,
    )
    from sase.agent.multi_prompt import parse_multi_prompt

    force_reuse_segment_envs: list[dict[str, str] | None] | None = None
    force_reuse_rewritten_prompt = rewrite_force_reuse_name_directives(prompt)
    if force_reuse_rewritten_prompt != prompt:
        # Parsing and syntax validation are both non-mutating. Complete them
        # before cleanup so malformed prompts and user-entered family phase
        # names cannot erase an existing agent before launch is rejected.
        force_reuse_prompts = parse_multi_prompt(prompt).segments
        try:
            preflight_launch_name_requests(
                force_reuse_prompts,
                allow_force_reuse=True,
            )
        except RuntimeError as exc:
            from sase.history.prompt import record_failed_launch_prompt

            record_failed_launch_prompt(original_submitted_prompt)
            if owns_context:
                app._prompt_context = None
            return _with_unresolved_warnings(
                LaunchTaskOutcome(str(exc), severity="error")
            )
        force_reuse_names = force_reuse_owner_names(force_reuse_prompts)
        force_reuse_bead_associations = force_reuse_bead_associations_by_prompt(
            force_reuse_prompts
        )
    else:
        force_reuse_names = []
        force_reuse_bead_associations = []
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
        prompt = force_reuse_rewritten_prompt
        from sase.agent.force_reuse_bead import force_reuse_bead_env

        force_reuse_segment_envs = [
            force_reuse_bead_env(association) or None
            for association in force_reuse_bead_associations
        ]

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
    bulk_patches = getattr(app, "_bulk_patches", None)
    if bulk_patches is None:
        bulk_patches = getattr(app, "_bulk_changespecs", None)
    if bulk_patches:
        app._bulk_patches = bulk_patches
        from sase.agent.multi_prompt import is_multi_prompt

        if is_multi_prompt(prompt):
            from sase.history.prompt import record_failed_launch_prompt

            record_failed_launch_prompt(prompt)
            app._bulk_patches = None
            if hasattr(app, "_bulk_changespecs"):
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

    with timer.stage("prompt_parse"):
        multi = parse_multi_prompt(prompt)
        from sase.agent.launch_projects import (
            enable_known_project_vcs_refs_for_launch_prompt,
        )

        enable_known_project_vcs_refs_for_launch_prompt("\n---\n".join(multi.segments))
    with timer.stage("xprompt_swarm_expand", segment_count=len(multi.segments)):
        if force_reuse_segment_envs is None:
            expanded_records = expand_xprompt_swarms_with_metadata(
                multi.segments, multi.local_xprompts
            )
        else:
            from itertools import count

            expanded_records = []
            expanded_segment_envs: list[dict[str, str] | None] = []
            group_counter = count()
            qualification_counter = count()
            for segment, env in zip(
                multi.segments, force_reuse_segment_envs, strict=True
            ):
                segment_records = expand_xprompt_swarms_with_metadata(
                    [segment],
                    multi.local_xprompts,
                    group_counter=group_counter,
                    qualification_counter=qualification_counter,
                )
                expanded_records.extend(segment_records)
                expanded_segment_envs.extend(
                    env if slot_index == 0 else None
                    for slot_index, _record in enumerate(segment_records)
                )
            force_reuse_segment_envs = expanded_segment_envs
        multi.segments = [record.prompt for record in expanded_records]
        multi.template_groups = [record.template_group for record in expanded_records]
        multi.swarm_xprompts = [
            getattr(record, "swarm_xprompts", ()) for record in expanded_records
        ]
        from sase.agent.agent_name_keys import resolve_agent_name_key_markers

        if len(multi.segments) == 1 and expanded_records[0].template_group is None:
            # Preserve local-xprompt frontmatter for the later single-agent
            # parse. parse_multi_prompt() deliberately strips it from
            # ``segments``, but no swarm expansion replaced this prompt.
            prompt = resolve_agent_name_key_markers([prompt])[0]
        else:
            multi.segments = resolve_agent_name_key_markers(multi.segments)
            if len(multi.segments) == 1:
                prompt = multi.segments[0]
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
            force_reuse_segment_envs,
        )
        return _with_unresolved_warnings(
            LaunchTaskOutcome(
                f"Multi-prompt launch queued for {ctx.display_name}",
                notify=False,
            )
        )

    single_extra_env: dict[str, str] | None = None
    if multi.swarm_xprompts and multi.swarm_xprompts[0]:
        from sase.xprompt.used_xprompts import (
            SASE_LAUNCH_SWARM_XPROMPTS,
            encode_launch_swarm_xprompts,
        )

        single_extra_env = {
            SASE_LAUNCH_SWARM_XPROMPTS: encode_launch_swarm_xprompts(
                multi.swarm_xprompts[0]
            )
        }
    if force_reuse_segment_envs:
        single_extra_env = _merge_extra_env(
            single_extra_env, force_reuse_segment_envs[0]
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
        extra_env=single_extra_env,
    )


def _merge_extra_env(
    base: dict[str, str] | None,
    extra: dict[str, str] | None,
) -> dict[str, str] | None:
    if not extra:
        return base
    merged = dict(base or {})
    merged.update(extra)
    return merged
