"""Low-level background agent spawn bridge for agent workflow actions."""

from __future__ import annotations


class BackgroundAgentLaunchMixin:
    """Mixin providing the TUI-to-runner subprocess bridge."""

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
        retry_transfer_from_pid: int | None = None,
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
                VCS reference. Used to set SASE_*_PRE_ALLOCATED env vars.
            extra_env: Additional environment variables to inject into the
                spawned subprocess (e.g. ``SASE_REPEAT_*`` for repeat fan-out).
            local_xprompts_file: Optional serialized local-xprompt file for the
                spawned subprocess.
            retry_transfer_from_pid: Optional parent PID that already owns the
                workspace claim and should transfer it to the child process.
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
            retry_transfer_from_pid=retry_transfer_from_pid,
        )
