"""Claude Code LLM provider implementation."""

import os
import subprocess
import uuid
from pathlib import Path

from sase.output import gemini_timer

from ._subprocess import stream_and_parse_json_output
from .base import LLMProvider
from .types import ModelTier

# Map model tiers to Claude CLI aliases
_TIER_TO_MODEL: dict[ModelTier, str] = {
    "large": "opus",
    "small": "sonnet",
}


def _log_interrupt(message: str, cycle: int) -> None:
    """Append an entry to the interrupt log in the artifacts directory."""
    import json
    import time

    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return
    log_path = Path(artifacts_dir) / "interrupt_log.jsonl"
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            json.dump(
                {"message": message, "timestamp": time.time(), "cycle": cycle},
                f,
            )
            f.write("\n")
    except OSError:
        pass


class ClaudeCodeProvider(LLMProvider):
    """LLM provider that invokes the Claude Code CLI tool."""

    _pending_interrupt_message: str | None = None

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

        current_prompt = prompt
        response_content = ""
        cycle = 0

        while True:
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

            if extra_args_env:
                for arg in extra_args_env.split():
                    base_args.append(arg)

            if timer_context:
                with timer_context:
                    content, stderr_content, return_code = self._run_subprocess(
                        base_args, current_prompt, suppress_output
                    )
                    print()
            else:
                content, stderr_content, return_code = self._run_subprocess(
                    base_args, current_prompt, suppress_output
                )

            # Check for user interrupt before checking return code.
            # When interrupted, the monitor thread terminates the process
            # (non-zero return code), but we should restart with the user's
            # message rather than treating it as an error.
            if self._pending_interrupt_message is not None:
                user_msg = self._pending_interrupt_message
                self._pending_interrupt_message = None
                cycle += 1
                _log_interrupt(user_msg, cycle)
                response_content = response_content.strip() + "\n\n" + content.strip()
                current_prompt = user_msg
                continue

            if return_code != 0:
                raise subprocess.CalledProcessError(
                    return_code,
                    base_args,
                    output=content,
                    stderr=stderr_content,
                )

            response_content = response_content.strip() + "\n\n" + content.strip()
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

        # Interrupt monitor: watch for interrupt_request.json from TUI
        artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
        if artifacts_dir:
            import json
            import threading
            import time

            interrupt_path = Path(artifacts_dir) / "interrupt_request.json"

            def _monitor_interrupt() -> None:
                while process.poll() is None:
                    if interrupt_path.exists():
                        try:
                            data = json.loads(
                                interrupt_path.read_text(encoding="utf-8")
                            )
                            self._pending_interrupt_message = data.get("message")
                            interrupt_path.unlink(missing_ok=True)
                            process.terminate()
                        except (OSError, json.JSONDecodeError):
                            pass
                        return
                    time.sleep(1.0)

            threading.Thread(target=_monitor_interrupt, daemon=True).start()

        # Stream JSON output and extract assistant text
        return stream_and_parse_json_output(process, suppress_output=suppress_output)
