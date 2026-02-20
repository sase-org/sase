"""Agent launch mixin for the ace TUI app."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from ._ref_resolution import _HG_REF_PATTERN
from ._types import PromptContext

if TYPE_CHECKING:
    from sase.ace.changespec import ChangeSpec
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

    def _finish_agent_launch(self, prompt: str) -> None:
        """Complete agent launch with the given prompt.

        Args:
            prompt: The user's prompt for the agent.
        """
        if self._prompt_context is None:
            self.notify("No prompt context - cannot launch", severity="error")  # type: ignore[attr-defined]
            return

        # Save prompt to history IMMEDIATELY (before background subprocess)
        from sase.prompt_history import add_or_update_prompt

        ctx = self._prompt_context
        add_or_update_prompt(
            prompt,
            project_name=ctx.project_name,
            branch_or_workspace=ctx.history_sort_key,
        )

        # Unmount prompt bar first
        self._unmount_prompt_bar()  # type: ignore[attr-defined]

        # Check if this is a bulk run
        if self._bulk_changespecs:
            self._launch_bulk_agents(prompt)
            return

        # Detect workspace-managing embedded workflows in home mode
        gh_ref_info: str | None = None
        git_ref_info: str | None = None
        hg_ref_info: str | None = None
        if ctx.is_home_mode:
            resolved = self._resolve_gh_from_prompt(prompt)  # type: ignore[attr-defined]
            if resolved is not None:
                (
                    ctx.project_file,
                    ctx.project_name,
                    ctx.workspace_dir,
                    ctx.workspace_num,
                    gh_ref_info,
                ) = resolved
                ctx.display_name = ctx.project_name
                ctx.update_target = ""  # gh.yml handles checkout
                ctx.is_home_mode = False  # Enable workspace claiming/releasing

        if ctx.is_home_mode and gh_ref_info is None:
            git_resolved = self._resolve_git_from_prompt(prompt)  # type: ignore[attr-defined]
            if git_resolved is not None:
                (
                    ctx.project_file,
                    ctx.project_name,
                    ctx.workspace_dir,
                    ctx.workspace_num,
                    git_ref_info,
                ) = git_resolved
                ctx.display_name = ctx.project_name
                ctx.update_target = ""  # git.yml handles checkout
                ctx.is_home_mode = False  # Enable workspace claiming/releasing

        if ctx.is_home_mode and gh_ref_info is None and git_ref_info is None:
            hg_resolved = self._resolve_hg_from_prompt(prompt)  # type: ignore[attr-defined]
            if hg_resolved is not None:
                (
                    ctx.project_file,
                    ctx.project_name,
                    ctx.workspace_dir,
                    ctx.workspace_num,
                    hg_ref_info,
                ) = hg_resolved
                ctx.display_name = ctx.project_name
                ctx.update_target = ""  # hg.yml handles checkout
                ctx.is_home_mode = False  # Enable workspace claiming/releasing

        # Also detect #hg in non-home mode: the ace(run) workspace and
        # the embedded #hg workflow must share the same workspace number,
        # so pass pre-allocation env vars to prevent #hg from allocating
        # a different workspace.
        if hg_ref_info is None and gh_ref_info is None and git_ref_info is None:
            hg_match = _HG_REF_PATTERN.search(prompt)
            if hg_match is not None:
                hg_ref_info = hg_match.group(1) or hg_match.group(2)

        # Check for workflow reference (e.g., #test_workflow or #split(arg1, arg2))
        # When VCS refs are present, strip them to find the core workflow reference
        workflow_prompt = prompt
        has_vcs_ref = (
            gh_ref_info is not None
            or git_ref_info is not None
            or hg_ref_info is not None
        )
        if has_vcs_ref:
            from ._ref_resolution import _GH_REF_PATTERN, _GIT_REF_PATTERN

            workflow_prompt = _GH_REF_PATTERN.sub("", workflow_prompt)
            workflow_prompt = _GIT_REF_PATTERN.sub("", workflow_prompt)
            workflow_prompt = _HG_REF_PATTERN.sub("", workflow_prompt)
            workflow_prompt = workflow_prompt.strip()

        if workflow_prompt.startswith("#"):
            workflow_result = self._try_execute_workflow(workflow_prompt)  # type: ignore[attr-defined]
            if workflow_result is True:
                # Full workflow executed successfully
                self._prompt_context = None
                self.call_later(self._load_agents)  # type: ignore[attr-defined]
                return
            elif not has_vcs_ref and isinstance(workflow_result, str):
                # Simple xprompt expanded inline — use as regular prompt
                # (with VCS refs, expansion happens in agent runner instead)
                prompt = workflow_result

        self._prompt_context = None

        # Launch single background agent
        self._launch_background_agent(
            cl_name=ctx.display_name,
            project_file=ctx.project_file,
            workspace_dir=ctx.workspace_dir,
            workspace_num=ctx.workspace_num,
            workflow_name=ctx.workflow_name,
            prompt=prompt,
            timestamp=ctx.timestamp,
            update_target=ctx.update_target,
            project_name=ctx.project_name,
            history_sort_key=ctx.history_sort_key,
            is_home_mode=ctx.is_home_mode,
            gh_ref=gh_ref_info,
            git_ref=git_ref_info,
            hg_ref=hg_ref_info,
        )

        # Refresh agents list (deferred to avoid lag)
        self.call_later(self._load_agents)  # type: ignore[attr-defined]
        self.notify(f"Agent started for {ctx.display_name}")  # type: ignore[attr-defined]

    def _launch_bulk_agents(self, prompt: str) -> None:
        """Launch agents for all bulk changespecs.

        Args:
            prompt: The user's prompt for all agents.
        """
        from sase.gh_workspace import detect_workflow_type_for_project
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

        for cs in changespecs:
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
            workflow_type = detect_workflow_type_for_project(project_file)
            cl_prompt = f"#{workflow_type}:{cl_name} {prompt}"

            # Determine which VCS ref to pass so _launch_background_agent
            # sets the SASE_*_PRE_ALLOCATED env vars correctly
            gh_ref: str | None = None
            git_ref: str | None = None
            hg_ref: str | None = None
            if workflow_type == "gh":
                gh_ref = cl_name
            elif workflow_type == "git":
                git_ref = cl_name
            elif workflow_type == "hg":
                hg_ref = cl_name

            self._launch_background_agent(
                cl_name=cl_name,
                project_file=project_file,
                workspace_dir=workspace_dir,
                workspace_num=workspace_num,
                workflow_name=workflow_name,
                prompt=cl_prompt,
                timestamp=timestamp,
                update_target=cl_name,
                project_name=project_name,
                history_sort_key=cl_name,
                gh_ref=gh_ref,
                git_ref=git_ref,
                hg_ref=hg_ref,
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
        gh_ref: str | None = None,
        git_ref: str | None = None,
        hg_ref: str | None = None,
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
            gh_ref: If set, the #gh reference that was pre-resolved by the TUI.
            git_ref: If set, the #git reference that was pre-resolved by the TUI.
            hg_ref: If set, the #hg reference that was pre-resolved by the TUI.
        """
        import subprocess
        import tempfile

        from sase.running_field import claim_workspace
        from sase.sase_utils import ensure_sase_directory
        from sase.shared_utils import convert_timestamp_to_artifacts_format

        # Write prompt to temp file (runner will read and delete)
        fd, prompt_file = tempfile.mkstemp(suffix=".md", prefix="sase_ace_prompt_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(prompt)

        # Get output file path
        workflows_dir = ensure_sase_directory("workflows")
        # Sanitize cl_name for filename
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in cl_name)
        output_path = os.path.join(
            workflows_dir, f"{safe_name}_ace-run-{timestamp}.txt"
        )

        # Build runner script path
        # From src/ace/tui/actions/agent_workflow/ we need 5 dirname calls to get to src/
        runner_script = os.path.join(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(
                        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    )
                )
            ),
            "axe_run_agent_runner.py",
        )

        # Build subprocess environment (copy to avoid mutating os.environ)
        subprocess_env = dict(os.environ)
        subprocess_env["SASE_AGENT"] = "1"
        if gh_ref is not None:
            subprocess_env["SASE_GH_PRE_ALLOCATED"] = "1"
            subprocess_env["SASE_GH_WORKSPACE_NUM"] = str(workspace_num)
            subprocess_env["SASE_GH_WORKSPACE_DIR"] = workspace_dir
        if git_ref is not None:
            subprocess_env["SASE_GIT_PRE_ALLOCATED"] = "1"
            subprocess_env["SASE_GIT_WORKSPACE_NUM"] = str(workspace_num)
            subprocess_env["SASE_GIT_WORKSPACE_DIR"] = workspace_dir
        if hg_ref is not None:
            subprocess_env["SASE_HG_PRE_ALLOCATED"] = "1"
            subprocess_env["SASE_HG_WORKSPACE_NUM"] = str(workspace_num)
            subprocess_env["SASE_HG_WORKSPACE_DIR"] = workspace_dir

        # Args: cl_name, project_file, workspace_dir, output_path, workspace_num,
        #       workflow_name, prompt_file, timestamp,
        #       update_target, project_name, history_sort_key, is_home_mode
        try:
            with open(output_path, "w") as output_file:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        runner_script,
                        cl_name,
                        project_file,
                        workspace_dir,
                        output_path,
                        str(workspace_num),
                        workflow_name,
                        prompt_file,
                        timestamp,
                        update_target,
                        project_name,
                        history_sort_key,
                        "1" if is_home_mode else "",
                    ],
                    cwd=workspace_dir,
                    stdout=output_file,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,  # Detach from TUI process
                    env=subprocess_env,
                )
        except Exception as e:
            self.notify(f"Failed to start agent: {e}", severity="error")  # type: ignore[attr-defined]
            return

        # Claim workspace so agent appears in Agents tab while running
        if not is_home_mode:
            artifacts_timestamp = convert_timestamp_to_artifacts_format(timestamp)
            if not claim_workspace(
                project_file,
                workspace_num,
                workflow_name,
                process.pid,
                cl_name,
                artifacts_timestamp=artifacts_timestamp,
            ):
                self.notify("Failed to claim workspace", severity="error")  # type: ignore[attr-defined]
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                return

        # Create home project directory and file if needed (for artifact path resolution)
        if is_home_mode:
            home_project_dir = os.path.expanduser("~/.sase/projects/home")
            home_project_file = os.path.join(home_project_dir, "home.gp")
            os.makedirs(home_project_dir, exist_ok=True)
            if not os.path.exists(home_project_file):
                with open(home_project_file, "w", encoding="utf-8") as f:
                    f.write("")  # Empty file - just needs to exist
