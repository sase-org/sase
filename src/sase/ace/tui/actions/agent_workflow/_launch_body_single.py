"""Single-prompt launch body helpers for agent workflow actions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ._launch_history import (
    record_launched_vcs_xprompt_usage,
    record_prompt_file_references,
    record_resolved_vcs_xprompt_usage,
    save_replayable_vcs_selection,
)
from ._launch_tasks import LaunchTaskOutcome, launch_results_tuple
from ._ref_resolution import strip_all_vcs_refs
from ._types import PromptContext
from ..failure_messages import with_log_panel_hint

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sase.agent.launch_types import AgentLaunchResult


def run_single_agent_launch_body(
    app: Any,
    *,
    prompt: str,
    ctx: PromptContext,
    owns_context: bool,
    original_submitted_prompt: str,
    submitted_xprompt: str,
    unresolved_warning_messages: Sequence[str],
    timer: Any,
    extra_env: dict[str, str] | None = None,
) -> LaunchTaskOutcome:
    """Run single-prompt, fan-out, repeat, workflow, and spawn launch paths."""
    from sase.project_display_names import project_display_name_for
    from sase.workspace_provider import get_ref_patterns, get_workflow_names
    from sase.xprompt._parsing import (
        extract_project_from_vcs_tag,
        extract_vcs_workflow_tag,
        normalize_default_vcs_workflow,
    )
    from sase.xprompt.directives import has_deferred_start_directive

    def _with_unresolved_warnings(
        outcome: LaunchTaskOutcome,
    ) -> LaunchTaskOutcome:
        return outcome.with_warning_messages(unresolved_warning_messages)

    # Capture these *before* normalization/resolution can mutate them.
    # ``entered_home_mode`` distinguishes a home-mode launch (where ctx is
    # baked from the last selection) from a project/patch launch.
    # ``had_explicit_vcs_tag`` records whether the *user* wrote a VCS tag,
    # so the unresolved-tag guard below does not fire for a plain prompt
    # that normalization later decorates with the default ``#git:home``.
    entered_home_mode = ctx.is_home_mode
    had_explicit_vcs_tag = extract_vcs_workflow_tag(prompt.strip() + " ") is not None

    with timer.stage("prompt_normalize"):
        if ctx.is_home_mode:
            prompt = normalize_default_vcs_workflow(prompt)

        has_wait = has_deferred_start_directive(prompt)

    # Resolve @name agent references in VCS tags (e.g. #gh:@d -> #gh:sase)
    # so the VCS ref pattern can match the resolved name for display_name.
    _vcs_prompt = prompt
    recorded_vcs_xprompt_usage = False
    with timer.stage("vcs_resolution", launch_kind="single_or_fanout"):
        try:
            from sase.axe.run_agent_phases import resolve_agent_refs_in_prompt

            _vcs_prompt, _ = resolve_agent_refs_in_prompt(prompt)
        except Exception:
            pass  # Agent not found - runner will resolve later

        # Detect workspace-managing embedded workflows in home mode.
        vcs_ref: tuple[str, str] | None = None  # (workflow_type, ref)
        known_project_vcs_fallback = False
        if ctx.is_home_mode:
            for wf_name in get_workflow_names():
                resolved = app._resolve_vcs_from_prompt(
                    _vcs_prompt,
                    wf_name,
                    skip_workspace=True,
                )
                if resolved is not None:
                    (
                        ctx.project_file,
                        ctx.project_name,
                        resolved_workspace_dir,
                        resolved_workspace_num,
                        ref_value,
                    ) = resolved
                    if has_wait:
                        ctx.workspace_dir = resolved_workspace_dir
                        ctx.workspace_num = resolved_workspace_num
                    else:
                        ctx.workspace_dir = ""
                        ctx.workspace_num = 0
                    vcs_ref = (wf_name, ref_value)
                    ctx.display_name = ref_value
                    ctx.history_sort_key = ref_value
                    ctx.update_target = ""  # workflow .yml handles checkout
                    # Enable workspace claiming/releasing for VCS workspaces.
                    ctx.is_home_mode = False
                    break
            if vcs_ref is None:
                from sase.agent.launcher import resolve_known_project_vcs_launch_ref

                known_ref = resolve_known_project_vcs_launch_ref(_vcs_prompt)
                if known_ref is not None:
                    from sase.vcs_provider import VCS_DEFAULT_REVISION

                    workspace_num = 0
                    workspace_dir = known_ref.workspace_dir if has_wait else ""

                    ctx.project_file = known_ref.project_file
                    ctx.project_name = known_ref.ref
                    ctx.workspace_dir = workspace_dir
                    ctx.workspace_num = workspace_num
                    ctx.display_name = known_ref.ref
                    ctx.history_sort_key = known_ref.ref
                    ctx.update_target = VCS_DEFAULT_REVISION
                    ctx.is_home_mode = False
                    vcs_ref = (known_ref.workflow_type, known_ref.ref)
                    known_project_vcs_fallback = True

        # Update the replayable saved selection to reflect the resolved VCS
        # ref from the actual submitted prompt. Without this, editing
        # ``#gh:sase-telegram`` to ``#gh:sase`` before submitting
        # would still replay as ``#gh:sase-telegram`` on the next Ctrl+Space.
        if vcs_ref is not None:
            save_replayable_vcs_selection(app, ctx, vcs_ref)

        if vcs_ref is not None:
            record_resolved_vcs_xprompt_usage(vcs_ref, ctx.project_name)
            recorded_vcs_xprompt_usage = True

    from sase.history.prompt import (
        add_or_update_prompt,
        record_failed_launch_prompt,
    )

    # A user-written, recognized leading VCS tag that resolved to nothing
    # must NOT silently launch under the baked home-mode identity. This is
    # the ``<ctrl+p>`` desync: the bar opens for one ref (ctx baked from the
    # last selection) and the user cycles to a different ref that no longer
    # resolves (e.g. a submitted/archived ``#gh:<patch>``). Falling
    # through here would launch in the *previous* ref's project/workspace
    # and skip the replay/MRU updates. Abort loudly instead.
    if entered_home_mode and had_explicit_vcs_tag and vcs_ref is None:
        leading_tag = extract_vcs_workflow_tag(_vcs_prompt.strip() + " ")
        if leading_tag is not None:
            ref_label = extract_project_from_vcs_tag(leading_tag) or leading_tag.strip()
            # Re-label history off the literal cycled ref, never the
            # unrelated baked project.
            ctx.display_name = ref_label
            ctx.history_sort_key = ref_label
            record_failed_launch_prompt(prompt)
            if owns_context:
                app._prompt_context = None
            timer.finish(dispatch="single", outcome="cancelled")
            err_msg = f"Cannot resolve {leading_tag.strip()}; not launching"
            return _with_unresolved_warnings(
                LaunchTaskOutcome(err_msg, severity="error")
            )

    # Save prompt after launch validation; validation failures are recorded
    # through the failed-launch helper so short prompts are retained.
    with timer.stage("history_write"):
        try:
            from sase.agent.launch_validation import validate_launch_name_requests

            validate_launch_name_requests([prompt])
        except RuntimeError as exc:
            err_msg = str(exc)
            record_failed_launch_prompt(prompt)
            if owns_context:
                app._prompt_context = None
            timer.finish(dispatch="single", outcome="cancelled")
            return _with_unresolved_warnings(
                LaunchTaskOutcome(err_msg, severity="error")
            )
        add_or_update_prompt(prompt)
        record_prompt_file_references(prompt)
    single_history_prompt = prompt

    # Also detect VCS refs in non-home mode: the ace(run) workspace and
    # the embedded workflow must share the same workspace number,
    # so pass pre-allocation env vars to prevent allocation of a
    # different workspace.
    known_project_vcs_ref: tuple[str, str] | None = None
    if vcs_ref is None:
        ref_patterns = get_ref_patterns()
        for wf_name, pattern in ref_patterns.items():
            match = pattern.search(_vcs_prompt)
            if match is not None:
                ref_value = match.group(1) or match.group(2)
                if ref_value:
                    vcs_ref = (wf_name, ref_value)
                    break
        if vcs_ref is None:
            from sase.xprompt._parsing import extract_known_project_vcs_ref

            known_project_vcs_ref = extract_known_project_vcs_ref(_vcs_prompt)
    if vcs_ref is not None and not recorded_vcs_xprompt_usage:
        record_launched_vcs_xprompt_usage(
            vcs_ref,
            prompt=_vcs_prompt,
            resolve_vcs_from_prompt=app._resolve_vcs_from_prompt,
        )
        recorded_vcs_xprompt_usage = True

    # Ensure %wait agents have a valid CWD when the VCS provider
    # doesn't provide a primary_workspace_dir.
    if has_wait and not ctx.is_home_mode and not ctx.workspace_dir:
        from sase.running_field import get_workspace_directory

        ctx.workspace_dir = get_workspace_directory(ctx.project_name, 1)

    # Check for workflow reference (e.g., #test_workflow or #split(arg1, arg2))
    # When VCS refs are present, strip them to find the core workflow reference.
    workflow_prompt = prompt
    if known_project_vcs_fallback:
        from sase.xprompt._parsing import strip_known_project_vcs_refs

        workflow_prompt = strip_known_project_vcs_refs(workflow_prompt)
    elif vcs_ref is not None:
        workflow_prompt = strip_all_vcs_refs(workflow_prompt)
    elif known_project_vcs_ref is not None:
        from sase.xprompt._parsing import strip_known_project_vcs_refs

        workflow_prompt = strip_known_project_vcs_refs(workflow_prompt)

    if workflow_prompt.startswith("#"):
        with timer.stage("workflow_dispatch"):
            workflow_result = app._try_execute_workflow(
                workflow_prompt,
                has_vcs_ref=vcs_ref is not None or known_project_vcs_ref is not None,
                submitted_prompt=original_submitted_prompt,
            )
        if workflow_result is True:
            # Full workflow executed successfully.
            if owns_context:
                app._prompt_context = None
            timer.finish(dispatch="workflow")
            return _with_unresolved_warnings(
                LaunchTaskOutcome(
                    "Workflow launch queued",
                    notify=False,
                    schedule_agents_refresh=True,
                )
            )
        elif vcs_ref is None and isinstance(workflow_result, str):
            # Simple xprompt expanded inline - use as regular prompt
            # (with VCS refs, expansion happens in agent runner instead).
            prompt = workflow_result

    # Parse user-prompt frontmatter for local xprompts.
    # (Multi-prompts were already caught by early detection above; this re-parse
    # handles single prompts whose text may have been modified by workflow check.)
    from sase.agent.multi_prompt import parse_multi_prompt

    with timer.stage("prompt_parse", pass_name="local_xprompts"):
        multi = parse_multi_prompt(prompt)
        local_xprompts = multi.local_xprompts

    raw_prompt = prompt

    if owns_context:
        app._prompt_context = None

    # Check for launch fan-out directives (e.g.,
    # %{%m:opus | %m:sonnet}, %alt(a,b), or %{a | b}).
    from sase.xprompt.directives import plan_prompt_fanout_variants
    from sase.xprompt.processor import (
        LAUNCH_DEFERRED_XPROMPT_NAMES,
        process_xprompt_references,
        prompt_may_reference_xprompt,
    )

    dispatch_prompt = "\n---\n".join(multi.segments)
    with timer.stage("fanout_plan", fanout_kind="prompt"):
        # Expand inline xprompt references before planning the fan-out shape.
        # The agent runner expands xprompts again in the subprocess; this TUI
        # pass is solely to discover the launch shape.
        if prompt_may_reference_xprompt(
            dispatch_prompt, extra_xprompts=local_xprompts or None
        ):
            planning_prompt = process_xprompt_references(
                dispatch_prompt,
                extra_xprompts=local_xprompts or None,
                defer_xprompt_names=LAUNCH_DEFERRED_XPROMPT_NAMES,
            )
        else:
            planning_prompt = dispatch_prompt
        fanout_plan = plan_prompt_fanout_variants(
            planning_prompt,
            extra_xprompts=local_xprompts or None,
        )
    if fanout_plan is not None:
        fanout_prompts = [slot.prompt for slot in fanout_plan.slots]
        timer.finish(
            dispatch=fanout_plan.launch_kind,
            slot_count=len(fanout_prompts),
        )
        # Synchronous task-queue staging; fan-out work runs in tracked workers.
        app.call_later(
            app._launch_multi_model_agents,
            [dispatch_prompt],
            ctx,
            vcs_ref,
            has_wait,
            fanout_plan.launch_kind,
            local_xprompts,
            submitted_xprompt,
            fanout_plan,
            extra_env,
        )
        return _with_unresolved_warnings(
            LaunchTaskOutcome(
                "Prompt fan-out launch queued for "
                f"{project_display_name_for(ctx.display_name)}",
                notify=False,
            )
        )

    # Check for repeat directive (e.g., %r:3). Fan out into N independent
    # top-level agents, each with its own workspace and agent_meta.json.
    from sase.agent.repeat_launcher import extract_repeat_and_name

    with timer.stage("fanout_plan", fanout_kind="repeat"):
        repeat_count, _, _ = extract_repeat_and_name(raw_prompt)
    if repeat_count is not None and repeat_count > 1:
        timer.finish(dispatch="repeat", slot_count=repeat_count)
        # Synchronous task-queue staging; repeat work runs in tracked workers.
        app.call_later(
            app._launch_repeat_agents,
            raw_prompt,
            ctx,
            vcs_ref,
            has_wait,
            extra_env,
        )
        return _with_unresolved_warnings(
            LaunchTaskOutcome(
                "Repeat launch queued for "
                f"{project_display_name_for(ctx.display_name)}",
                notify=False,
            )
        )

    # For agents with %wait directives, override workspace to deferred
    # (workspace_num=0) so no real workspace is claimed until dependencies
    # resolve.
    if has_wait and not ctx.is_home_mode and ctx.workspace_num != 0:
        from sase.running_field import get_workspace_directory

        with timer.stage("workspace_directory_resolution", deferred=True):
            ctx.workspace_num = 0
            ctx.workspace_dir = get_workspace_directory(ctx.project_name, 1)

    # Launch single background agent from this worker thread. Pass raw
    # (unexpanded) prompt so the runner saves the original user input as
    # raw_xprompt.md.
    display_name = ctx.display_name
    try:
        with timer.stage("low_level_spawn"):
            from sase.agent.launch_executor import (
                LaunchExecutionContext,
                LaunchSpawnRequest,
                execute_launch_plan,
            )
            from sase.core.agent_launch_facade import plan_fake_fanout

            fixed_workspace = ctx.is_home_mode or has_wait

            def _spawn_from_tui(request: LaunchSpawnRequest) -> AgentLaunchResult:
                return app._launch_background_agent(
                    cl_name=request.cl_name,
                    project_file=request.project_file,
                    workspace_dir=request.workspace_dir,
                    workspace_num=request.workspace_num,
                    workflow_name=request.workflow_name,
                    prompt=request.prompt,
                    timestamp=request.timestamp,
                    update_target=request.update_target,
                    project_name=request.project_name,
                    history_sort_key=request.history_sort_key,
                    is_home_mode=request.is_home_mode,
                    vcs_ref=request.vcs_ref,
                    deferred_workspace=request.deferred_workspace,
                    extra_env=request.extra_env,
                    local_xprompts_file=request.local_xprompts_file,
                    retry_transfer_from_pid=request.transfer_from_pid,
                )

            execution = execute_launch_plan(
                plan_fake_fanout("single", [raw_prompt]),
                LaunchExecutionContext(
                    cl_name=ctx.display_name,
                    project_file=ctx.project_file,
                    project_name=ctx.project_name,
                    update_target=ctx.update_target,
                    history_sort_key=ctx.history_sort_key,
                    is_home_mode=ctx.is_home_mode,
                    vcs_ref=vcs_ref,
                    deferred_workspace=has_wait,
                    workspace_num=ctx.workspace_num if fixed_workspace else None,
                    workspace_dir=ctx.workspace_dir if fixed_workspace else None,
                    use_preallocated_workspace=False,
                ),
                spawn=_spawn_from_tui,
                base_timestamp=ctx.timestamp,
                extra_env=extra_env,
            )
        timer.finish(dispatch="single")
        return _with_unresolved_warnings(
            LaunchTaskOutcome(
                f"Agent started for {project_display_name_for(display_name)}",
                results=launch_results_tuple(execution.results),
            )
        )
    except Exception as exc:
        record_failed_launch_prompt(single_history_prompt)
        timer.finish(dispatch="single", outcome="error")
        log.exception("Agent launch failed")
        from sase.logs import log_launch_failure

        log_launch_failure(
            kind="single",
            display_name=display_name,
            exc=exc,
            project=ctx.project_name,
            workspace_num=ctx.workspace_num,
            prompt_preview=single_history_prompt,
            vcs_ref=None if vcs_ref is None else f"{vcs_ref[0]}:{vcs_ref[1]}",
        )
        return _with_unresolved_warnings(
            LaunchTaskOutcome(
                with_log_panel_hint("Agent launch failed"),
                severity="error",
            )
        )
