"""Gemini LLM provider implementation."""

import os
import subprocess
import time
from pathlib import Path

from sase.output import gemini_timer

from ._hookspec import hookimpl
from ._subprocess import (
    start_interrupt_monitor,
    stream_and_parse_gemini_json_output,
    stream_process_output,  # noqa: F401 - backward-compat re-export
)
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
    def llm_provider_short_name(self) -> str:
        return "gem"

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
    def llm_model_short_aliases(self) -> dict[str, str]:
        return {
            "gemini-3-flash-preview": "flash3",
            "gemini-3.1-pro-preview": "pro31p",
            "gemini-3.1-pro": "pro31",
            "gemini-2.5-flash": "flash25",
            "gemini-2.5-pro": "pro25",
            "gemini-2.0-flash": "flash20",
        }

    @hookimpl
    def llm_skill_template_context(self) -> dict[str, str]:
        return {
            "provider_name": "Gemini",
            "provider_tool_name": "Gemini CLI",
            "provider_native_ask_tool": "ask_user",
        }

    @hookimpl
    def llm_additional_skill_deploy_subpaths(self) -> list[str]:
        return [".gemini/jetski"]

    @hookimpl
    def llm_autodetect_priority(self) -> int:
        return 30

    @hookimpl
    def llm_autodetect_cli_name(self) -> str:
        return "gemini"

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
            "--output-format",
            "stream-json",
            "--yolo",
            "--model",
            model,
        ]

        timer_context = (
            gemini_timer("Waiting for Gemini") if not suppress_output else None
        )

        current_prompt = prompt
        accumulated_response = ""
        total_usage: dict[str, int] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
        cycle = 0

        while True:
            if timer_context:
                with timer_context:
                    response_content, stderr_content, return_code, usage = (
                        self._run_subprocess(base_args, current_prompt, suppress_output)
                    )
                    print()
            else:
                response_content, stderr_content, return_code, usage = (
                    self._run_subprocess(base_args, current_prompt, suppress_output)
                )

            for key in total_usage:
                total_usage[key] += usage.get(key, 0)

            # Check for user interrupt before error handling
            if self._pending_interrupt_message is not None:
                user_msg = self._pending_interrupt_message
                self._pending_interrupt_message = None
                cycle += 1
                _log_interrupt(user_msg, cycle)
                accumulated_response = (
                    accumulated_response + "\n\n" + response_content.strip()
                ).strip()
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

            accumulated_response = (
                accumulated_response + "\n\n" + response_content.strip()
            ).strip()
            return InvokeResult(
                content=accumulated_response,
                usage=total_usage,
            )

    # ------------------------------------------------------------------
    # Subprocess runner
    # ------------------------------------------------------------------

    def _run_subprocess(
        self,
        args: list[str],
        prompt: str,
        suppress_output: bool,
    ) -> tuple[str, str, int, dict[str, int]]:
        """Run the Gemini CLI subprocess.

        Args:
            args: Command-line arguments.
            prompt: Prompt to write to stdin.
            suppress_output: If True, suppress output.

        Returns:
            Tuple of (stdout_content, stderr_content, return_code, usage).
        """
        env = os.environ.copy()
        env["TERM"] = "dumb"
        env["NO_COLOR"] = "1"

        process = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )

        # Write prompt to stdin
        if process.stdin:
            process.stdin.write(prompt)
            process.stdin.close()

        start_interrupt_monitor(
            process,
            on_interrupt=lambda msg: setattr(self, "_pending_interrupt_message", msg),
        )

        return stream_and_parse_gemini_json_output(
            process, suppress_output=suppress_output
        )
