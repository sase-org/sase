"""Agent launch mixin for the ace TUI app."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ._launch_bulk import BulkLaunchMixin
from ._launch_multi_model import MultiModelLaunchMixin
from ._launch_multi_prompt import MultiPromptLaunchMixin
from ._launch_repeat import RepeatLaunchMixin
from ._ref_resolution import is_non_workspace_workflow, strip_all_vcs_refs
from ._types import PromptContext

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sase.ace.changespec import ChangeSpec
    from sase.ace.tui.modals import SelectionItem
    from sase.ace.tui.models import Agent


def _record_prompt_file_references(prompt: str) -> None:
    """Extract and record file references from *prompt* into history."""
    from sase.history.file_references import (
        extract_recordable_file_refs,
        record_file_references,
    )

    refs = extract_recordable_file_refs(prompt)
    if refs:
        record_file_references(refs)


class AgentLaunchMixin(
    MultiModelLaunchMixin,
    RepeatLaunchMixin,
    MultiPromptLaunchMixin,
    BulkLaunchMixin,
):
    """Internal mixin providing agent launching functionality."""

    # Type hints for attributes accessed from AceApp (defined at runtime)
    changespecs: list[ChangeSpec]
    marked_indices: set[int]
    _agents: list[Agent]

    # State for bulk agent runs (from AgentWorkflowMixin)
    _bulk_changespecs: list[ChangeSpec] | None = None
    # State for prompt input (from AgentWorkflowMixin)
    _prompt_context: PromptContext | None = None
    # State for repeat-last-@/<space> selection (from EntryPointsMixin)
    _last_custom_agent_selection: SelectionItem | None = None

    def _finish_agent_launch(self, prompt: str) -> None:
        """Complete agent launch with the given prompt.

        Unmounts the prompt bar immediately, then runs the heavy launch
        work (VCS resolution, history writes, xprompt expansion, subprocess
        spawn) in a worker thread via ``asyncio.to_thread`` so the Textual
        event loop stays responsive to keystrokes (notably ``j``/``k``)
        during the blocking I/O portion of the launch.

        Args:
            prompt: The user's prompt for the agent.
        """
        if self._prompt_context is None:
            self.notify("No prompt context - cannot launch", severity="error")  # type: ignore[attr-defined]
            return

        # Regenerate timestamp at launch time (not when prompt bar was opened)
        from sase.core.agent_launch_facade import reserve_launch_timestamp_batch

        ctx = self._prompt_context
        ctx.timestamp = reserve_launch_timestamp_batch(1)[0]
        ctx.workflow_name = f"ace(run)-{ctx.timestamp}"

        # Unmount prompt bar first (transfers focus to the active tab's list
        # widget, see _transfer_focus_off_prompt_bar), then offload the
        # heavy launch path to a worker thread.
        self._unmount_prompt_bar()  # type: ignore[attr-defined]
        self.notify(f"Launching agent for {ctx.display_name}...")  # type: ignore[attr-defined]

        self.call_later(self._run_agent_launch_body_async, prompt)  # type: ignore[attr-defined]

    async def _run_agent_launch_body_async(self, prompt: str) -> None:
        """Run :meth:`_run_agent_launch_body` in a worker thread.

        Keeps blocking I/O (disk reads, history writes, xprompt expansion)
        off the Textual event loop so ``j``/``k`` keystrokes entered
        immediately after submitting the launch are dispatched promptly.
        """
        import asyncio

        try:
            await asyncio.to_thread(self._run_agent_launch_body, prompt)
        except Exception:
            log.exception("Agent launch body failed")
            self.notify(  # type: ignore[attr-defined]
                "Agent launch failed (see log)", severity="error"
            )

    def _run_agent_launch_body(self, prompt: str) -> None:
        """Heavy body of ``_finish_agent_launch``, run in a worker thread.

        Executes blocking I/O (VCS resolution, history writes, xprompt
        expansion, workflow dispatch) off the Textual event-loop thread.
        UI-touching calls (``self.notify``, sub-launch helpers that mutate
        widget state) are marshalled back to the main thread via
        ``self.call_later``.
        """
        if self._prompt_context is None:
            # Context was cleared between the submit and the worker tick
            # (e.g. another launch path ran); nothing to do.
            return
        ctx = self._prompt_context
        from sase.agent.launch_timing import LaunchTimingRecorder

        timer = LaunchTimingRecorder(
            "tui_agent_launch",
            {
                "prompt_len": len(prompt),
                "project_name": ctx.project_name,
                "home_mode": ctx.is_home_mode,
            },
        )

        # Check if this is a bulk run
        if self._bulk_changespecs:
            from sase.agent.multi_prompt import is_multi_prompt

            if is_multi_prompt(prompt):
                self.call_later(  # type: ignore[attr-defined]
                    lambda: self.notify(  # type: ignore[attr-defined]
                        "Multi-prompt is not supported with bulk launch",
                        severity="error",
                    )
                )
                self._bulk_changespecs = None
                self._prompt_context = None
                return
            self.call_later(self._launch_bulk_agents, prompt)  # type: ignore[attr-defined]
            return

        from sase.workspace_provider import get_ref_patterns, get_workflow_names
        from sase.xprompt.directives import has_wait_directive
        from sase.xprompt._parsing import (
            normalize_default_vcs_workflow,
            normalize_default_vcs_workflow_segment,
        )

        # Detect multi-agent xprompts before injecting the default workspace
        # ref; a multi-agent xprompt must still look like the sole top-level
        # reference in its segment.
        from sase.agent.multi_agent_xprompt import expand_multi_agent_xprompts
        from sase.agent.multi_prompt import parse_multi_prompt

        with timer.stage("prompt_parse"):
            multi = parse_multi_prompt(prompt)
        with timer.stage(
            "multi_agent_xprompt_expand", segment_count=len(multi.segments)
        ):
            multi.segments = expand_multi_agent_xprompts(
                multi.segments, multi.local_xprompts
            )
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
                    pass  # Agent not found — runner will resolve later

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
            from sase.history.prompt import add_or_update_prompt

            with timer.stage("history_write", launch_kind="multi_prompt"):
                add_or_update_prompt(
                    normalized_prompt,
                    project_name=ctx.project_name,
                    branch_or_workspace=ctx.history_sort_key,
                )
                _record_prompt_file_references(normalized_prompt)
            self._prompt_context = None
            timer.finish(dispatch="multi_prompt", segment_count=len(multi.segments))
            self.call_later(  # type: ignore[attr-defined]
                self._launch_multi_prompt_agents, multi, ctx, mp_vcs_ref
            )
            return

        with timer.stage("prompt_normalize"):
            if ctx.is_home_mode:
                prompt = normalize_default_vcs_workflow(prompt)

            has_wait = has_wait_directive(prompt)

        # Resolve @name agent references in VCS tags (e.g. #gh:@d → #gh:sase)
        # so the VCS ref pattern can match the resolved name for display_name.
        _vcs_prompt = prompt
        with timer.stage("vcs_resolution", launch_kind="single_or_fanout"):
            try:
                from sase.axe.run_agent_phases import resolve_agent_refs_in_prompt

                _vcs_prompt, _ = resolve_agent_refs_in_prompt(prompt)
            except Exception:
                pass  # Agent not found — runner will resolve later

            # Record VCS xprompt usage for MRU cycling
            from sase.xprompt._parsing import extract_vcs_workflow_tag

            _vcs_tag = extract_vcs_workflow_tag(_vcs_prompt)
            if _vcs_tag:
                from sase.history.vcs_xprompt_mru import record_vcs_xprompt_usage

                record_vcs_xprompt_usage(_vcs_tag.strip())

            # Detect workspace-managing embedded workflows in home mode
            vcs_ref: tuple[str, str] | None = None  # (workflow_type, ref)
            known_project_vcs_fallback = False
            if ctx.is_home_mode:
                for wf_name in get_workflow_names():
                    resolved = self._resolve_vcs_from_prompt(  # type: ignore[attr-defined]
                        _vcs_prompt, wf_name, skip_workspace=has_wait
                    )
                    if resolved is not None:
                        (
                            ctx.project_file,
                            ctx.project_name,
                            ctx.workspace_dir,
                            ctx.workspace_num,
                            ref_value,
                        ) = resolved
                        vcs_ref = (wf_name, ref_value)
                        ctx.display_name = ref_value
                        ctx.history_sort_key = ref_value
                        ctx.update_target = ""  # workflow .yml handles checkout
                        if is_non_workspace_workflow(wf_name):
                            ctx.is_home_mode = True
                        else:
                            # Enable workspace claiming/releasing for VCS workspaces.
                            ctx.is_home_mode = False
                        break
                if vcs_ref is None:
                    from sase.agent.launcher import resolve_known_project_vcs_launch_ref

                    known_ref = resolve_known_project_vcs_launch_ref(_vcs_prompt)
                    if known_ref is not None:
                        from sase.running_field import (
                            get_first_available_axe_workspace,
                            get_workspace_directory_for_num,
                        )
                        from sase.vcs_provider import VCS_DEFAULT_REVISION

                        workspace_num = 0
                        workspace_dir = known_ref.workspace_dir
                        if not has_wait:
                            workspace_num = get_first_available_axe_workspace(
                                known_ref.project_file
                            )
                            workspace_dir, _ = get_workspace_directory_for_num(
                                workspace_num, known_ref.ref
                            )

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

            # Update `,<space>` saved selection to reflect the resolved VCS
            # ref from the actual submitted prompt.  Without this, editing
            # ``#gh:sase-telegram`` to ``#gh:sase`` before submitting
            # would still replay as ``#gh:sase-telegram`` on the next
            # `,<space>`.
            if vcs_ref is not None and not is_non_workspace_workflow(vcs_ref[0]):
                from ...modals import SelectionItem
                from sase.ace.last_agent_selection import save_last_agent_selection

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
                self._last_custom_agent_selection = sel
                save_last_agent_selection(sel)

        # Save prompt to history after VCS resolution so project/branch are correct
        from sase.history.prompt import add_or_update_prompt

        with timer.stage("history_write"):
            add_or_update_prompt(
                prompt,
                project_name=ctx.project_name,
                branch_or_workspace=ctx.history_sort_key,
            )
            _record_prompt_file_references(prompt)

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

        # Ensure %wait agents have a valid CWD when the VCS provider
        # doesn't provide a primary_workspace_dir (e.g. hg).
        if has_wait and not ctx.is_home_mode and not ctx.workspace_dir:
            from sase.running_field import get_workspace_directory

            ctx.workspace_dir = get_workspace_directory(ctx.project_name, 1)

        # Check for workflow reference (e.g., #test_workflow or #split(arg1, arg2))
        # When VCS refs are present, strip them to find the core workflow reference
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
                workflow_result = self._try_execute_workflow(  # type: ignore[attr-defined]
                    workflow_prompt,
                    has_vcs_ref=vcs_ref is not None
                    or known_project_vcs_ref is not None,
                )
            if workflow_result is True:
                # Full workflow executed successfully
                self._prompt_context = None
                timer.finish(dispatch="workflow")
                self.call_later(self._schedule_agents_async_refresh)  # type: ignore[attr-defined]
                return
            elif vcs_ref is None and isinstance(workflow_result, str):
                # Simple xprompt expanded inline — use as regular prompt
                # (with VCS refs, expansion happens in agent runner instead)
                prompt = workflow_result

        # Parse user-prompt frontmatter for local xprompts.
        # (Multi-prompts were already caught by early detection above;
        # this re-parse handles single prompts whose text may have been
        # modified by the workflow check.)
        with timer.stage("prompt_parse", pass_name="local_xprompts"):
            multi = parse_multi_prompt(prompt)
            local_xprompts = multi.local_xprompts

        raw_prompt = prompt

        self._prompt_context = None

        # Check for launch fan-out directives (e.g., %m(opus,sonnet) or %alt(a,b)).
        from sase.xprompt.directives import plan_prompt_fanout_variants

        dispatch_prompt = "\n---\n".join(multi.segments)
        with timer.stage("fanout_plan", fanout_kind="prompt"):
            fanout_plan = plan_prompt_fanout_variants(
                dispatch_prompt,
                extra_xprompts=local_xprompts or None,
            )
        if fanout_plan is None:
            # Expand inline xprompt references (e.g., #swarm → %m(opus,sonnet))
            # only when the prompt has a lexical xprompt candidate.  The agent
            # runner expands xprompts again in the subprocess; this TUI pass is
            # solely to discover xprompt-injected fan-out directives.
            from sase.xprompt.processor import (
                process_xprompt_references,
                prompt_may_reference_xprompt,
            )

            if prompt_may_reference_xprompt(
                dispatch_prompt, extra_xprompts=local_xprompts or None
            ):
                expanded_prompt = process_xprompt_references(
                    dispatch_prompt,
                    extra_xprompts=local_xprompts or None,
                )
                fanout_plan = plan_prompt_fanout_variants(
                    expanded_prompt,
                    extra_xprompts=local_xprompts or None,
                )
        if fanout_plan is not None:
            fanout_prompts = [slot.prompt for slot in fanout_plan.slots]
            timer.finish(
                dispatch=fanout_plan.launch_kind,
                slot_count=len(fanout_prompts),
            )
            self.call_later(  # type: ignore[attr-defined]
                self._launch_multi_model_agents,
                fanout_prompts,
                ctx,
                vcs_ref,
                has_wait,
                fanout_plan.launch_kind,
            )
            return

        # Check for repeat directive (e.g., %r:3). Fan out into N independent
        # top-level agents, each with its own workspace and agent_meta.json.
        from sase.agent.repeat_launcher import extract_repeat_and_name

        with timer.stage("fanout_plan", fanout_kind="repeat"):
            repeat_count, _, _ = extract_repeat_and_name(raw_prompt)
        if repeat_count is not None and repeat_count > 1:
            timer.finish(dispatch="repeat", slot_count=repeat_count)
            self.call_later(  # type: ignore[attr-defined]
                self._launch_repeat_agents, raw_prompt, ctx, vcs_ref, has_wait
            )
            return

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

                def _spawn_from_tui(request: LaunchSpawnRequest) -> None:
                    self._launch_background_agent(
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
                    )

                execute_launch_plan(
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
                        workspace_num=ctx.workspace_num,
                        workspace_dir=ctx.workspace_dir,
                        use_preallocated_workspace=True,
                    ),
                    spawn=_spawn_from_tui,
                    base_timestamp=ctx.timestamp,
                )
            timer.finish(dispatch="single")
            self.call_later(self._schedule_agents_async_refresh)  # type: ignore[attr-defined]
            msg = f"Agent started for {display_name}"
            self.call_later(lambda: self.notify(msg))  # type: ignore[attr-defined]
        except Exception:
            timer.finish(dispatch="single", outcome="error")
            log.exception("Agent launch failed")
            self.call_later(  # type: ignore[attr-defined]
                lambda: self.notify(  # type: ignore[attr-defined]
                    "Agent launch failed (see log)", severity="error"
                )
            )

    def _launch_background_agent(
        self,
        cl_name: str,
        project_file: str,
        workspace_dir: str,
        workspace_num: int,
        workflow_name: str,
        prompt: str,
        timestamp: str,
        update_target: str = "",
        project_name: str = "",
        history_sort_key: str = "",
        is_home_mode: bool = False,
        vcs_ref: tuple[str, str] | None = None,
        deferred_workspace: bool = False,
        extra_env: dict[str, str] | None = None,
        local_xprompts_file: str | None = None,
    ) -> None:
        """Launch agent as background process.

        Args:
            cl_name: Display name for the CL/project.
            project_file: Path to the project file.
            workspace_dir: Path to the workspace directory.
            workspace_num: The workspace number.
            workflow_name: Name for the workflow.
            prompt: The user's prompt for the agent.
            timestamp: Shared timestamp for artifacts.
            update_target: What to checkout (CL name or "p4head").
            project_name: Project name for prompt history tracking.
            history_sort_key: CL name to associate with the prompt in history.
            is_home_mode: If True, skip workspace management (for home directory).
            vcs_ref: If set, a (workflow_type, ref) tuple for the pre-resolved
                VCS reference.  Used to set SASE_*_PRE_ALLOCATED env vars.
            extra_env: Additional environment variables to inject into the
                spawned subprocess (e.g. ``SASE_REPEAT_*`` for repeat fan-out).
            local_xprompts_file: Optional serialized local-xprompt file for the
                spawned subprocess.
        """
        from sase.agent.launcher import spawn_agent_subprocess

        spawn_agent_subprocess(
            cl_name=cl_name,
            project_file=project_file,
            workspace_dir=workspace_dir,
            workspace_num=workspace_num,
            workflow_name=workflow_name,
            prompt=prompt,
            timestamp=timestamp,
            update_target=update_target,
            project_name=project_name,
            history_sort_key=history_sort_key,
            is_home_mode=is_home_mode,
            vcs_ref=vcs_ref,
            deferred_workspace=deferred_workspace,
            extra_env=extra_env,
            local_xprompts_file=local_xprompts_file,
        )
