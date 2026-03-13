"""Claude Code LLM provider implementation."""

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

from sase.rich_utils import gemini_timer

from ._plan_utils import (
    append_plan_feedback_log,
    read_plan_feedback,
    save_plan_to_sase,
    write_plan_path_artifact,
)
from ._subprocess import stream_and_parse_json_output
from .base import LLMProvider
from .types import ModelTier

# Map model tiers to Claude CLI aliases
_TIER_TO_MODEL: dict[ModelTier, str] = {
    "large": "opus",
    "small": "sonnet",
}

# Maximum number of plan feedback retry rounds before giving up
_MAX_PLAN_FEEDBACK_RETRIES = 5


def _find_plan_file() -> str | None:
    """Find the most recently modified .md plan file.

    Searches common plan directories for the most recently modified markdown
    file.
    """
    search_dirs = [
        Path.home() / ".claude" / "plans",
        Path.home() / ".gemini" / "plans",
        Path.home() / ".codex" / "plans",
    ]
    md_files: list[Path] = []
    for d in search_dirs:
        if d.is_dir():
            md_files.extend(d.glob("*.md"))
    if not md_files:
        return None
    return str(max(md_files, key=lambda f: f.stat().st_mtime))


class ClaudeCodeProvider(LLMProvider):
    """LLM provider that invokes the Claude Code CLI tool."""

    def resolve_model_name(self, model_tier: ModelTier = "large") -> str:
        """Return the Claude model alias for the given tier."""
        return _TIER_TO_MODEL[model_tier]

    def invoke(
        self,
        prompt: str,
        *,
        model_tier: ModelTier,
        suppress_output: bool = False,
        model_override: str | None = None,
    ) -> str:
        """Invoke Claude Code CLI with the given prompt.

        Args:
            prompt: The preprocessed prompt to send.
            model_tier: Which model tier to use ("large" or "small").
            suppress_output: If True, suppress real-time output to console.
            model_override: If set, use this model name directly instead of
                mapping from ``model_tier``.

        Returns:
            The response text from Claude.

        Raises:
            subprocess.CalledProcessError: If the Claude CLI process fails.
        """
        model_alias = model_override if model_override else _TIER_TO_MODEL[model_tier]
        is_plan_mode = bool(os.environ.get("SASE_AGENT_PLAN_MODE"))

        # Parse additional args from environment variable based on tier
        # Check generic SASE_LLM_*_ARGS first, fall back to Claude-specific
        if model_tier == "large":
            extra_args_env = os.environ.get(
                "SASE_LLM_LARGE_ARGS", os.environ.get("SASE_CLAUDE_LARGE_ARGS")
            )
        else:
            extra_args_env = os.environ.get(
                "SASE_LLM_SMALL_ARGS", os.environ.get("SASE_CLAUDE_SMALL_ARGS")
            )

        timer_context = (
            gemini_timer("Waiting for Claude") if not suppress_output else None
        )

        # Plan feedback retry loop: when the user rejects a plan with feedback,
        # Claude Code in pipe mode exits instead of revising.  We detect this
        # via plan_response.json and re-launch phase 1 with the feedback
        # appended to the prompt.
        current_prompt = prompt
        plan_session_uuid: str | None = None
        response_content = ""
        stderr_content = ""
        return_code = 0
        base_args: list[str] = []
        approval_dir = Path()
        marker_path = Path()

        for retry_round in range(_MAX_PLAN_FEEDBACK_RETRIES + 1):
            session_uuid = str(uuid.uuid4())
            base_args = [
                "claude",
                "-p",
                "--verbose",
                "--model",
                model_alias,
                "--output-format",
                "stream-json",
                "--dangerously-skip-permissions",
                "--session-id",
                session_uuid,
            ]

            if is_plan_mode:
                base_args.append("--permission-mode=plan")

            if extra_args_env:
                for arg in extra_args_env.split():
                    base_args.append(arg)

            approval_dir = Path.home() / ".sase" / "plan_approval" / session_uuid
            marker_path = approval_dir / "plan_approved.marker"

            # Track first planning session for sidecar link
            if plan_session_uuid is None:
                plan_session_uuid = session_uuid

            if timer_context:
                with timer_context:
                    response_content, stderr_content, return_code = (
                        self._run_subprocess(
                            base_args,
                            current_prompt,
                            suppress_output,
                            plan_marker_path=marker_path,
                        )
                    )
                    print()
            else:
                response_content, stderr_content, return_code = self._run_subprocess(
                    base_args,
                    current_prompt,
                    suppress_output,
                    plan_marker_path=marker_path,
                )

            # Check if plan was approved BEFORE checking return code.
            # When the monitoring thread terminates the process (due to
            # ExitPlanMode loop), the return code is non-zero (signal),
            # but we should proceed to phase 2 rather than raising an error.
            if marker_path.exists():
                break  # Plan approved — fall through to phase 2

            # In plan mode, check if the user rejected with feedback.
            # Claude Code in pipe mode doesn't reliably revise after a hook
            # denial, so we re-launch phase 1 with the feedback included.
            if is_plan_mode and return_code != 0:
                feedback = read_plan_feedback(approval_dir)
                if feedback:
                    append_plan_feedback_log(feedback, retry_round)
                    # Find the plan file Claude wrote so we can include it
                    plan_file = _find_plan_file()
                    if plan_file:
                        try:
                            plan_content = Path(plan_file).read_text(encoding="utf-8")
                        except OSError:
                            plan_content = None
                    else:
                        plan_content = None

                    if plan_content:
                        current_prompt = (
                            f"{prompt}\n\n"
                            f"--- Previous Plan ---\n{plan_content}\n"
                            f"--- User Feedback ---\n{feedback}\n\n"
                            "Please revise the plan based on the feedback "
                            "above and resubmit it."
                        )
                    else:
                        current_prompt = (
                            f"{prompt}\n\n"
                            f"--- User Feedback on Previous Plan ---\n"
                            f"{feedback}\n\n"
                            "Please revise the plan based on the feedback "
                            "above and resubmit it."
                        )

                    # Clean up old approval directory before retry
                    shutil.rmtree(approval_dir, ignore_errors=True)
                    continue  # Retry phase 1 with feedback

            # No marker and no feedback retry — check if process failed
            if return_code != 0:
                raise subprocess.CalledProcessError(
                    return_code,
                    base_args,
                    output=response_content,
                    stderr=stderr_content,
                )

            # return_code == 0, no marker — normal completion (no plan mode)
            return response_content.strip()

        # --- Plan approved: proceed to phase 2 (implementation) ---
        if not marker_path.exists():
            # Exhausted retries without approval
            raise subprocess.CalledProcessError(
                return_code,
                base_args,
                output=response_content,
                stderr=stderr_content,
            )

        plan_file_path = marker_path.read_text().strip()
        # Clean up the approval directory
        shutil.rmtree(approval_dir)

        if plan_file_path:
            saved_plan_path = save_plan_to_sase(plan_file_path)
            write_plan_path_artifact(saved_plan_path)
        else:
            saved_plan_path = None

        impl_session_uuid = str(uuid.uuid4())

        # Write sidecar link so thinking panel finds both plan + impl sessions
        try:
            cwd = os.getcwd()
            hashed_cwd = re.sub(r"[^a-zA-Z0-9]", "-", cwd)
            claude_project_dir = Path.home() / ".claude" / "projects" / hashed_cwd
            if claude_project_dir.is_dir():
                link_file = claude_project_dir / f"{plan_session_uuid}.impl_session"
                link_file.write_text(impl_session_uuid)
        except OSError:
            pass  # Best-effort; thinking panel still works without it

        impl_args = [
            "claude",
            "-p",
            "--verbose",
            "--model",
            model_alias,
            "--output-format",
            "stream-json",
            "--dangerously-skip-permissions",
            "--session-id",
            impl_session_uuid,
        ]
        if extra_args_env:
            for arg in extra_args_env.split():
                impl_args.append(arg)

        if saved_plan_path:
            impl_prompt = (
                f"@{saved_plan_path}\n\n"
                "The above plan has been reviewed and approved. "
                "Implement it now."
            )
        else:
            impl_prompt = (
                "Your plan has been reviewed and approved by the user. "
                "Proceed with implementing the plan now."
            )

        if timer_context:
            with gemini_timer("Implementing plan"):
                impl_content, impl_stderr, impl_rc = self._run_subprocess(
                    impl_args, impl_prompt, suppress_output
                )
                print()
        else:
            impl_content, impl_stderr, impl_rc = self._run_subprocess(
                impl_args, impl_prompt, suppress_output
            )

        if impl_rc != 0:
            raise subprocess.CalledProcessError(
                impl_rc,
                impl_args,
                output=impl_content,
                stderr=impl_stderr,
            )

        # Combine phase 1 + phase 2 response text
        response_content = response_content.strip() + "\n\n" + impl_content.strip()
        return response_content.strip()

    def _run_subprocess(
        self,
        args: list[str],
        prompt: str,
        suppress_output: bool,
        plan_marker_path: Path | None = None,
    ) -> tuple[str, str, int]:
        """Run the Claude CLI subprocess.

        Args:
            args: Command-line arguments.
            prompt: Prompt to write to stdin.
            suppress_output: If True, suppress output.
            plan_marker_path: If set, monitor this marker file and terminate
                the process when it appears. This handles the edge case where
                Claude Code's internal plan mode state machine fails to exit
                after plan approval in pipe mode.

        Returns:
            Tuple of (stdout_content, stderr_content, return_code).
        """
        process = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Write prompt to stdin
        if process.stdin:
            process.stdin.write(prompt)
            process.stdin.close()

        if plan_marker_path:
            import threading
            import time

            def _monitor_marker() -> None:
                while process.poll() is None:
                    if plan_marker_path.exists():
                        try:
                            process.terminate()
                        except OSError:
                            pass
                        return
                    time.sleep(1.0)

            threading.Thread(target=_monitor_marker, daemon=True).start()

        # Stream JSON output and extract assistant text
        return stream_and_parse_json_output(process, suppress_output=suppress_output)
