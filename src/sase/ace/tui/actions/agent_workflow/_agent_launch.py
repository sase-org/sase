"""Agent launch mixin for the ace TUI app."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

from ._launch_bulk import BulkLaunchMixin
from ._launch_multi_model import MultiModelLaunchMixin
from ._launch_multi_prompt import MultiPromptLaunchMixin
from ._launch_repeat import RepeatLaunchMixin
from ._ref_resolution import strip_all_vcs_refs
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
        from sase.core.time import generate_timestamp

        ctx = self._prompt_context
        ctx.timestamp = generate_timestamp()
        ctx.workflow_name = f"ace(run)-{ctx.timestamp}"

        # Unmount prompt bar first (transfers focus to the active tab's list
        # widget, see _transfer_focus_off_prompt_bar), then offload the
        # heavy launch path to a worker thread.
        self._unmount_prompt_bar()  # type: ignore[attr-defined]

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

        has_wait = has_wait_directive(prompt)

        # Resolve @name agent references in VCS tags (e.g. #gh:@d → #gh:sase)
        # so the VCS ref pattern can match the resolved name for display_name.
        _vcs_prompt = prompt
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

        # --- Early multi-prompt detection ---
        # Detect multi-prompts BEFORE VCS resolution to match the CLI
        # (sase run) behavior: each segment handles its own VCS resolution
        # in the agent runner, avoiding per-segment workspace allocation
        # at the TUI level.
        from sase.agent.multi_prompt import parse_multi_prompt

        multi = parse_multi_prompt(prompt)
        if len(multi.segments) > 1:
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

            add_or_update_prompt(
                prompt,
                project_name=ctx.project_name,
                branch_or_workspace=ctx.history_sort_key,
            )
            _record_prompt_file_references(prompt)
            self._prompt_context = None
            self.call_later(  # type: ignore[attr-defined]
                self._launch_multi_prompt_agents, multi, ctx, mp_vcs_ref
            )
            return

        # Detect workspace-managing embedded workflows in home mode
        vcs_ref: tuple[str, str] | None = None  # (workflow_type, ref)
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
                    ctx.is_home_mode = False  # Enable workspace claiming/releasing
                    break

            # Update `,<space>` saved selection to reflect the resolved VCS
            # ref from the actual submitted prompt.  Without this, editing
            # ``#gh:sase-telegram`` to ``#gh:sase`` before submitting
            # would still replay as ``#gh:sase-telegram`` on the next
            # `,<space>`.
            if vcs_ref is not None:
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
        if vcs_ref is None:
            ref_patterns = get_ref_patterns()
            for wf_name, pattern in ref_patterns.items():
                match = pattern.search(_vcs_prompt)
                if match is not None:
                    ref_value = match.group(1) or match.group(2)
                    if ref_value:
                        vcs_ref = (wf_name, ref_value)
                        break

        # Ensure %wait agents have a valid CWD when the VCS provider
        # doesn't provide a primary_workspace_dir (e.g. hg).
        if has_wait and not ctx.is_home_mode and not ctx.workspace_dir:
            from sase.running_field import get_workspace_directory

            ctx.workspace_dir = get_workspace_directory(ctx.project_name, 1)

        # Check for workflow reference (e.g., #test_workflow or #split(arg1, arg2))
        # When VCS refs are present, strip them to find the core workflow reference
        workflow_prompt = prompt
        if vcs_ref is not None:
            workflow_prompt = strip_all_vcs_refs(workflow_prompt)

        if workflow_prompt.startswith("#"):
            workflow_result = self._try_execute_workflow(  # type: ignore[attr-defined]
                workflow_prompt, has_vcs_ref=vcs_ref is not None
            )
            if workflow_result is True:
                # Full workflow executed successfully
                self._prompt_context = None
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
        multi = parse_multi_prompt(prompt)
        local_xprompts = multi.local_xprompts

        # Expand inline xprompt references (e.g., #swarm → %m(opus,sonnet))
        # so multi-model directives from xprompts are detected below.
        # Keep the raw prompt (with frontmatter) for the agent runner
        # to parse again and expand local xprompts in the subprocess.
        from sase.xprompt.processor import process_xprompt_references

        raw_prompt = prompt
        prompt = process_xprompt_references(
            "\n---\n".join(multi.segments),
            extra_xprompts=local_xprompts or None,
        )

        self._prompt_context = None

        # Check for multi-model directive (e.g., %m(opus,sonnet))
        from sase.xprompt.directives import split_prompt_for_models

        model_prompts = split_prompt_for_models(prompt)
        if model_prompts is not None:
            self.call_later(  # type: ignore[attr-defined]
                self._launch_multi_model_agents,
                model_prompts,
                ctx,
                vcs_ref,
                has_wait,
            )
            return

        # Check for repeat directive (e.g., %r:3). Fan out into N independent
        # top-level agents, each with its own workspace and agent_meta.json.
        from sase.agent.repeat_launcher import extract_repeat_and_name

        repeat_count, _, _ = extract_repeat_and_name(raw_prompt)
        if repeat_count is not None and repeat_count > 1:
            self.call_later(  # type: ignore[attr-defined]
                self._launch_repeat_agents, raw_prompt, ctx, vcs_ref, has_wait
            )
            return

        # For agents with %wait directives, override workspace to deferred
        # (workspace_num=0) so no real workspace is claimed until dependencies
        # resolve.
        if has_wait and not ctx.is_home_mode and ctx.workspace_num != 0:
            from sase.running_field import get_workspace_directory

            ctx.workspace_num = 0
            ctx.workspace_dir = get_workspace_directory(ctx.project_name, 1)

        # Launch single background agent in a thread — pass raw (unexpanded)
        # prompt so the runner saves the original user input as raw_xprompt.md.
        display_name = ctx.display_name

        def _run() -> None:
            try:
                self._launch_background_agent(
                    cl_name=ctx.display_name,
                    project_file=ctx.project_file,
                    workspace_dir=ctx.workspace_dir,
                    workspace_num=ctx.workspace_num,
                    workflow_name=ctx.workflow_name,
                    prompt=raw_prompt,
                    timestamp=ctx.timestamp,
                    update_target=ctx.update_target,
                    project_name=ctx.project_name,
                    history_sort_key=ctx.history_sort_key,
                    is_home_mode=ctx.is_home_mode,
                    vcs_ref=vcs_ref,
                    deferred_workspace=has_wait,
                )
                self.call_later(self._schedule_agents_async_refresh)  # type: ignore[attr-defined]
                msg = f"Agent started for {display_name}"
                self.call_later(lambda: self.notify(msg))  # type: ignore[attr-defined]
            except Exception:
                log.exception("Agent launch failed")
                self.call_later(  # type: ignore[attr-defined]
                    lambda: self.notify(  # type: ignore[attr-defined]
                        "Agent launch failed (see log)", severity="error"
                    )
                )

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        msg = f"Launching agent for {display_name}..."
        self.call_later(lambda: self.notify(msg))  # type: ignore[attr-defined]

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
        """
        from sase.agent.launcher import spawn_agent_subprocess

        try:
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
            )
        except Exception as e:
            log.exception("Failed to start agent for %s", cl_name)
            err_msg = f"Failed to start agent: {e}"
            self.call_later(  # type: ignore[attr-defined]
                lambda: self.notify(err_msg, severity="error")  # type: ignore[attr-defined]
            )
