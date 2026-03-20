"""Agent launch mixin for the ace TUI app."""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING

from ._ref_resolution import strip_all_vcs_refs
from ._types import PromptContext

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from sase.ace.changespec import ChangeSpec
    from sase.ace.tui.modals import SelectionItem
    from sase.ace.tui.models import Agent


class AgentLaunchMixin:
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

        Args:
            prompt: The user's prompt for the agent.
        """
        if self._prompt_context is None:
            self.notify("No prompt context - cannot launch", severity="error")  # type: ignore[attr-defined]
            return

        # Regenerate timestamp at launch time (not when prompt bar was opened)
        from sase.sase_utils import generate_timestamp

        ctx = self._prompt_context
        ctx.timestamp = generate_timestamp()
        ctx.workflow_name = f"ace(run)-{ctx.timestamp}"

        # Save prompt to history IMMEDIATELY (before background subprocess)
        from sase.prompt_history import add_or_update_prompt

        add_or_update_prompt(
            prompt,
            project_name=ctx.project_name,
            branch_or_workspace=ctx.history_sort_key,
        )

        # Unmount prompt bar first
        self._unmount_prompt_bar()  # type: ignore[attr-defined]

        # Check if this is a bulk run
        if self._bulk_changespecs:
            from sase.multi_prompt import is_multi_prompt

            if is_multi_prompt(prompt):
                self.notify(  # type: ignore[attr-defined]
                    "Multi-prompt is not supported with bulk launch", severity="error"
                )
                self._bulk_changespecs = None
                self._prompt_context = None
                return
            self._launch_bulk_agents(prompt)
            return

        from sase.workspace_provider import get_ref_patterns, get_workflow_names
        from sase.xprompt.directives import has_wait_directive

        has_wait = has_wait_directive(prompt)

        # --- Early multi-prompt detection ---
        # Detect multi-prompts BEFORE VCS resolution to match the CLI
        # (sase run) behavior: each segment handles its own VCS resolution
        # in the agent runner, avoiding per-segment workspace allocation
        # at the TUI level.
        from sase.multi_prompt import parse_multi_prompt

        multi = parse_multi_prompt(prompt)
        if len(multi.segments) > 1:
            mp_vcs_ref: tuple[str, str] | None = None
            ref_patterns = get_ref_patterns()
            for wf_name, pattern in ref_patterns.items():
                match = pattern.search(prompt)
                if match is not None:
                    ref_value = match.group(1) or match.group(2)
                    if ref_value:
                        mp_vcs_ref = (wf_name, ref_value)
                        ctx.display_name = ref_value
                        break
            self._prompt_context = None
            self._launch_multi_prompt_agents(multi, ctx, mp_vcs_ref)
            return

        # Detect workspace-managing embedded workflows in home mode
        vcs_ref: tuple[str, str] | None = None  # (workflow_type, ref)
        if ctx.is_home_mode:
            for wf_name in get_workflow_names():
                resolved = self._resolve_vcs_from_prompt(  # type: ignore[attr-defined]
                    prompt, wf_name, skip_workspace=has_wait
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

        # Also detect VCS refs in non-home mode: the ace(run) workspace and
        # the embedded workflow must share the same workspace number,
        # so pass pre-allocation env vars to prevent allocation of a
        # different workspace.
        if vcs_ref is None:
            ref_patterns = get_ref_patterns()
            for wf_name, pattern in ref_patterns.items():
                match = pattern.search(prompt)
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
            workflow_result = self._try_execute_workflow(workflow_prompt)  # type: ignore[attr-defined]
            if workflow_result is True:
                # Full workflow executed successfully
                self._prompt_context = None
                self.call_later(self._load_agents)  # type: ignore[attr-defined]
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
            self._launch_multi_model_agents(model_prompts, ctx, vcs_ref, has_wait)
            return

        # For agents with %wait directives, override workspace to deferred
        # (workspace_num=0) so no real workspace is claimed until dependencies
        # resolve.
        if has_wait and not ctx.is_home_mode and ctx.workspace_num != 0:
            from sase.running_field import get_workspace_directory

            ctx.workspace_num = 0
            ctx.workspace_dir = get_workspace_directory(ctx.project_name, 1)

        # Launch single background agent — pass raw (unexpanded) prompt so
        # the runner saves the original user input as raw_xprompt.md.
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

        # Refresh agents list (deferred to avoid lag)
        self.call_later(self._load_agents)  # type: ignore[attr-defined]
        self.notify(f"Agent started for {ctx.display_name}")  # type: ignore[attr-defined]

    def _launch_multi_model_agents(
        self,
        model_prompts: list[str],
        ctx: PromptContext,
        vcs_ref: tuple[str, str] | None,
        has_wait: bool,
    ) -> None:
        """Launch one agent per model for a multi-model directive.

        Each prompt in *model_prompts* already has the multi-model directive
        (e.g. ``%m(opus,sonnet)``) replaced with a single ``%model:X``.

        Args:
            model_prompts: Per-model prompts to launch.
            ctx: The prompt context with project/workspace info.
            vcs_ref: Resolved VCS reference, if any.
            has_wait: Whether the prompt has ``%wait`` directives.
        """
        from sase.running_field import (
            get_first_available_axe_workspace,
            get_workspace_directory,
            get_workspace_directory_for_num,
        )
        from sase.sase_utils import generate_timestamp

        launched = 0
        for i, model_prompt in enumerate(model_prompts):
            if i > 0:
                time.sleep(1)

            timestamp = generate_timestamp()
            workflow_name = f"ace(run)-{timestamp}"

            if has_wait and not ctx.is_home_mode:
                workspace_num = 0
                workspace_dir = get_workspace_directory(ctx.project_name, 1)
            elif ctx.is_home_mode:
                workspace_num = ctx.workspace_num
                workspace_dir = ctx.workspace_dir
            else:
                workspace_num = get_first_available_axe_workspace(ctx.project_file)
                workspace_dir, _ = get_workspace_directory_for_num(
                    workspace_num, ctx.project_name
                )

            self._launch_background_agent(
                cl_name=ctx.display_name,
                project_file=ctx.project_file,
                workspace_dir=workspace_dir,
                workspace_num=workspace_num,
                workflow_name=workflow_name,
                prompt=model_prompt,
                timestamp=timestamp,
                update_target=ctx.update_target,
                project_name=ctx.project_name,
                history_sort_key=ctx.history_sort_key,
                is_home_mode=ctx.is_home_mode,
                vcs_ref=vcs_ref,
                deferred_workspace=has_wait,
            )
            launched += 1

        self.call_later(self._load_agents)  # type: ignore[attr-defined]
        self.notify(f"Started {launched} agent(s) for {ctx.display_name}")  # type: ignore[attr-defined]

    def _launch_multi_prompt_agents(
        self,
        multi: object,
        ctx: PromptContext,
        vcs_ref: tuple[str, str] | None,
    ) -> None:
        """Launch each multi-prompt segment as a separate agent.

        Delegates to ``launch_multi_prompt_agents()`` in a background thread
        to avoid blocking the TUI event loop during naming-wait polls.
        """
        from sase.multi_prompt import MultiPrompt
        from sase.multi_prompt_launcher import launch_multi_prompt_agents

        assert isinstance(multi, MultiPrompt)

        import threading

        def _run() -> None:
            try:
                results = launch_multi_prompt_agents(
                    segments=multi.segments,
                    local_xprompts=multi.local_xprompts,
                    cl_name=ctx.display_name,
                    project_file=ctx.project_file,
                    project_name=ctx.project_name,
                    is_home_mode=ctx.is_home_mode,
                    vcs_ref=vcs_ref,
                    on_agent_spawned=lambda: self.call_later(self._load_agents),  # type: ignore[attr-defined]
                )
                self.call_later(self._load_agents)  # type: ignore[attr-defined]
                msg = f"Started {len(results)} agent(s) for {ctx.display_name}"
                self.call_later(lambda: self.notify(msg))  # type: ignore[attr-defined]
            except Exception:
                log.exception("Multi-prompt launch failed")
                self.call_later(  # type: ignore[attr-defined]
                    lambda: self.notify(  # type: ignore[attr-defined]
                        "Multi-prompt launch failed (see log)", severity="error"
                    )
                )

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        # Immediate feedback while agents launch in background.
        n = len(multi.segments)
        self.call_later(self._load_agents)  # type: ignore[attr-defined]
        self.notify(f"Launching {n} agent(s) for {ctx.display_name}...")  # type: ignore[attr-defined]

    def _launch_bulk_agents(self, prompt: str) -> None:
        """Launch agents for all bulk changespecs.

        Args:
            prompt: The user's prompt for all agents.
        """
        from sase.workspace_provider import detect_workflow_type
        from sase.sase_utils import generate_timestamp
        from sase.running_field import (
            get_first_available_axe_workspace,
            get_workspace_directory_for_num,
        )

        if not self._bulk_changespecs:
            self.notify("No bulk changespecs", severity="error")  # type: ignore[attr-defined]
            return

        changespecs = self._bulk_changespecs
        self._bulk_changespecs = None
        self._prompt_context = None

        launched_count = 0
        failed_count = 0

        for i, cs in enumerate(changespecs):
            if i > 0:
                time.sleep(1)
            project_name = cs.project_basename
            cl_name = cs.name

            project_file = os.path.expanduser(
                f"~/.sase/projects/{project_name}/{project_name}.gp"
            )

            if not os.path.isfile(project_file):
                self.notify(f"No project file for {cl_name}", severity="warning")  # type: ignore[attr-defined]
                failed_count += 1
                continue

            try:
                workspace_num = get_first_available_axe_workspace(project_file)
                timestamp = generate_timestamp()
                workflow_name = f"ace(run)-{timestamp}"
                workspace_dir, _ = get_workspace_directory_for_num(
                    workspace_num, project_name
                )
            except RuntimeError as e:
                self.notify(f"Workspace error for {cl_name}: {e}", severity="warning")  # type: ignore[attr-defined]
                failed_count += 1
                continue

            # Detect VCS type and build per-CL prompt with prefix
            workflow_type = detect_workflow_type(project_file)
            cl_prompt = f"#{workflow_type}:{cl_name} {prompt}"

            self._launch_background_agent(
                cl_name=cl_name,
                project_file=project_file,
                workspace_dir=workspace_dir,
                workspace_num=workspace_num,
                workflow_name=workflow_name,
                prompt=cl_prompt,
                timestamp=timestamp,
                update_target="" if workflow_type else cl_name,
                project_name=project_name,
                history_sort_key=cl_name,
                vcs_ref=(workflow_type, cl_name),
            )
            launched_count += 1

        # Clear marks after bulk launch
        self.marked_indices = set()  # type: ignore[assignment]
        self._refresh_display()  # type: ignore[attr-defined]

        # Refresh agents list
        self.call_later(self._load_agents)  # type: ignore[attr-defined]

        # Show summary notification
        if failed_count > 0:
            self.notify(  # type: ignore[attr-defined]
                f"Started {launched_count} agent(s), {failed_count} failed",
                severity="warning",
            )
        else:
            self.notify(f"Started {launched_count} agent(s)")  # type: ignore[attr-defined]

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
        """
        from sase.agent_launcher import spawn_agent_subprocess

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
            )
        except Exception as e:
            log.exception("Failed to start agent for %s", cl_name)
            self.notify(f"Failed to start agent: {e}", severity="error")  # type: ignore[attr-defined]
