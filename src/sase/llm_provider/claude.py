"""Claude Code LLM provider implementation."""

import os
import subprocess
import uuid
from pathlib import Path

from sase.rich_utils import gemini_timer

from ._subprocess import stream_and_parse_json_output
from .base import LLMProvider
from .types import ModelTier

# Map model tiers to Claude CLI aliases
_TIER_TO_MODEL: dict[ModelTier, str] = {
    "large": "opus",
    "small": "sonnet",
}


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

        # Build base command arguments
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

        if extra_args_env:
            for arg in extra_args_env.split():
                base_args.append(arg)

        # Start the process and stream output in real-time with timer
        timer_context = (
            gemini_timer("Waiting for Claude") if not suppress_output else None
        )

        if timer_context:
            with timer_context:
                response_content, stderr_content, return_code = self._run_subprocess(
                    base_args, prompt, suppress_output
                )
                # Add newline to separate agent output from timer
                print()
        else:
            response_content, stderr_content, return_code = self._run_subprocess(
                base_args, prompt, suppress_output
            )

        # Check if process failed
        if return_code != 0:
            error_content = f"Error running claude command (exit code {return_code})"
            if stderr_content:
                error_content += f": {stderr_content.strip()}"
            raise subprocess.CalledProcessError(
                return_code,
                base_args,
                output=response_content,
                stderr=stderr_content,
            )

        # Check if plan was approved — if so, resume session for implementation
        marker_path = (
            Path.home()
            / ".sase"
            / "plan_approval"
            / session_uuid
            / "plan_approved.marker"
        )
        if marker_path.exists():
            marker_path.unlink()

            resume_args = [
                "claude",
                "-p",
                "--resume",
                session_uuid,
                "--verbose",
                "--model",
                model_alias,
                "--output-format",
                "stream-json",
                "--dangerously-skip-permissions",
            ]
            if extra_args_env:
                for arg in extra_args_env.split():
                    resume_args.append(arg)

            resume_prompt = (
                "Your plan has been reviewed and approved by the user. "
                "Proceed with implementing the plan now."
            )

            if timer_context:
                with gemini_timer("Implementing plan"):
                    impl_content, impl_stderr, impl_rc = self._run_subprocess(
                        resume_args, resume_prompt, suppress_output
                    )
                    print()
            else:
                impl_content, impl_stderr, impl_rc = self._run_subprocess(
                    resume_args, resume_prompt, suppress_output
                )

            if impl_rc != 0:
                raise subprocess.CalledProcessError(
                    impl_rc,
                    resume_args,
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
    ) -> tuple[str, str, int]:
        """Run the Claude CLI subprocess.

        Args:
            args: Command-line arguments.
            prompt: Prompt to write to stdin.
            suppress_output: If True, suppress output.

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

        # Stream JSON output and extract assistant text
        return stream_and_parse_json_output(process, suppress_output=suppress_output)
