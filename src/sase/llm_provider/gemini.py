"""Gemini LLM provider implementation."""

import os
import pty
import subprocess
import termios
import time
from pathlib import Path

from sase.output import gemini_timer

from ._hookspec import hookimpl
from ._subprocess import start_interrupt_monitor, stream_process_output
from .base import LLMProvider
from .types import InvokeResult, ModelTier

_DEFAULT_MODEL = "gemini-3-flash-preview"


def _gemini_bin() -> str:
    """Return the path to the Gemini CLI binary."""
    return os.environ.get("SASE_GEMINI_PATH", "gemini")


def _log_interrupt(message: str, cycle: int) -> None:
    """Append an entry to the interrupt log in the artifacts directory."""
    import json

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


class GeminiProvider(LLMProvider):
    """LLM provider that invokes Google's Gemini CLI tool."""

    _pending_interrupt_message: str | None = None

    def resolve_model_name(self, model_tier: ModelTier = "large") -> str:  # noqa: ARG002
        """Return the Gemini model name."""
        return _DEFAULT_MODEL

    @hookimpl
    def llm_provider_name(self) -> str:
        return "gemini"

    @hookimpl
    def llm_resolve_model_name(self, model_tier: ModelTier) -> str:
        return self.resolve_model_name(model_tier)

    @hookimpl
    def llm_known_model_names(self) -> list[str]:
        return [
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-3.1-pro",
            "gemini-3.1-pro-preview",
            "gemini-3-flash-preview",
            "gemini-2.0-flash",
        ]

    @hookimpl
    def llm_skill_template_context(self) -> dict[str, str]:
        return {
            "provider_name": "Gemini",
            "provider_tool_name": "Gemini CLI",
            "provider_native_ask_tool": "ask_user",
        }

    @hookimpl
    def llm_autodetect_priority(self) -> int:
        return 30

    @hookimpl
    def llm_autodetect_cli_name(self) -> str | None:
        # Gemini is the always-eligible fallback — no CLI presence check.
        return None

    @hookimpl
    def llm_invoke(
        self,
        prompt: str,
        model_tier: ModelTier,
        suppress_output: bool,
        model_override: str | None,
    ) -> InvokeResult:
        return self.invoke(
            prompt,
            model_tier=model_tier,
            suppress_output=suppress_output,
            model_override=model_override,
        )

    def invoke(
        self,
        prompt: str,
        *,
        model_tier: ModelTier,  # noqa: ARG002
        suppress_output: bool = False,
        model_override: str | None = None,
    ) -> InvokeResult:
        """Invoke Gemini CLI with the given prompt.

        Args:
            prompt: The preprocessed prompt to send.
            model_tier: Unused. Accepted for interface compatibility.
            suppress_output: If True, suppress real-time output to console.
            model_override: If set, use this model instead of the default.

        Returns:
            An ``InvokeResult`` with the response text (usage is ``None``).

        Raises:
            subprocess.CalledProcessError: If the Gemini CLI process fails.
        """
        model = model_override or _DEFAULT_MODEL

        base_args = [
            _gemini_bin(),
            "--yolo",
            "--model",
            model,
        ]

        timer_context = (
            gemini_timer("Waiting for Gemini") if not suppress_output else None
        )

        current_prompt = prompt
        accumulated_response = ""
        cycle = 0

        while True:
            if timer_context:
                with timer_context:
                    response_content, stderr_content, return_code = (
                        self._run_subprocess(base_args, current_prompt, suppress_output)
                    )
                    print()
            else:
                response_content, stderr_content, return_code = self._run_subprocess(
                    base_args, current_prompt, suppress_output
                )

            # Check for user interrupt before error handling
            if self._pending_interrupt_message is not None:
                user_msg = self._pending_interrupt_message
                self._pending_interrupt_message = None
                cycle += 1
                _log_interrupt(user_msg, cycle)
                accumulated_response += response_content
                # Gemini has no session persistence — reconstruct context
                current_prompt = (
                    f"{prompt}\n\n"
                    f"--- Your Previous Response ---\n{accumulated_response}\n\n"
                    f"--- User Follow-up ---\n{user_msg}"
                )
                continue

            if return_code != 0:
                raise subprocess.CalledProcessError(
                    return_code,
                    base_args,
                    output=response_content,
                    stderr=stderr_content,
                )

            return InvokeResult(
                content=(accumulated_response + response_content).strip()
            )

    # ------------------------------------------------------------------
    # Subprocess runner
    # ------------------------------------------------------------------

    def _run_subprocess(
        self,
        args: list[str],
        prompt: str,
        suppress_output: bool,
    ) -> tuple[str, str, int]:
        """Run the Gemini CLI subprocess.

        Uses a PTY for stdout so that the Gemini CLI uses line-buffered
        output (instead of block-buffered pipes), enabling real-time
        streaming into ``live_reply.md`` for the TUI.

        Args:
            args: Command-line arguments.
            prompt: Prompt to write to stdin.
            suppress_output: If True, suppress output.

        Returns:
            Tuple of (stdout_content, stderr_content, return_code).
        """
        # Create a PTY pair so Gemini CLI sees a terminal on stdout and
        # flushes output line-by-line instead of block-buffering.
        master_fd, slave_fd = pty.openpty()

        # Disable output post-processing (OPOST) to prevent the PTY
        # line discipline from converting \n → \r\n.
        try:
            attrs = termios.tcgetattr(slave_fd)
            attrs[1] &= ~termios.OPOST
            termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)
        except termios.error:
            pass

        env = os.environ.copy()
        env["TERM"] = "dumb"
        env["NO_COLOR"] = "1"

        process = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=slave_fd,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        os.close(slave_fd)  # Parent doesn't need the slave end

        # Wrap the PTY master as a text stream so stream_process_output
        # can read from it exactly like a regular pipe.
        pty_stdout = open(  # noqa: SIM115
            master_fd, encoding="utf-8", closefd=True
        )
        process.stdout = pty_stdout  # type: ignore[assignment]

        # Write prompt to stdin
        if process.stdin:
            process.stdin.write(prompt)
            process.stdin.close()

        start_interrupt_monitor(
            process,
            on_interrupt=lambda msg: setattr(self, "_pending_interrupt_message", msg),
        )

        # Stream output in real-time with ANSI stripping (the PTY may
        # cause Gemini CLI to emit terminal control codes).
        try:
            return stream_process_output(
                process, suppress_output=suppress_output, clean_ansi=True
            )
        finally:
            pty_stdout.close()
