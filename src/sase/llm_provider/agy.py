"""Antigravity (`agy`) LLM provider implementation.

This is the MVP plain-stdout provider for Google's Antigravity CLI (`agy`),
the replacement for the retired consumer Gemini CLI. The Antigravity CLI does
not currently document a machine-readable JSON/stream output mode, so this
provider streams plain stdout through the shared
:func:`stream_process_output` helper and returns ``usage=None``. Tool-call,
usage, and thinking artifacts are intentionally unsupported until a stable
``agy`` machine-readable contract exists (see the epic plan at
``sdd/epics/202606/agy_provider_mvp.md``).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from sase.output import gemini_timer

from ._hookspec import hookimpl
from ._subprocess import start_interrupt_monitor, stream_process_output
from .base import LLMProvider
from .types import InvokeResult, ModelTier

_TIER_TO_MODEL: dict[ModelTier, str] = {
    "large": "Gemini 3.5 Flash (High)",
    "small": "Gemini 3.5 Flash (Low)",
}
_AGY_PATH_ENV = "SASE_AGY_PATH"
_AGY_PRINT_TIMEOUT_ENV = "SASE_AGY_PRINT_TIMEOUT"
# Antigravity's built-in `--print-timeout` default is 5m, which is far too
# short for long agentic SASE runs. Default to a generous, overridable window;
# the value is a Go duration string as accepted by `agy --print-timeout`.
_DEFAULT_PRINT_TIMEOUT = "24h"


def _agy_bin() -> str:
    """Return the Antigravity CLI executable SASE should launch."""
    return os.environ.get(_AGY_PATH_ENV, "agy")


def _agy_print_timeout() -> str:
    """Return the `agy --print-timeout` duration (Go duration string)."""
    return os.environ.get(_AGY_PRINT_TIMEOUT_ENV, _DEFAULT_PRINT_TIMEOUT)


def _agy_executable_not_found_error(command: str) -> FileNotFoundError:
    """Build an actionable missing-Antigravity diagnostic."""
    return FileNotFoundError(
        "Unable to launch Antigravity CLI executable "
        f"{command!r}. Set SASE_AGY_PATH to the Antigravity (`agy`) binary or "
        "ensure 'agy' is discoverable on PATH."
    )


def _log_interrupt(message: str | None, cycle: int) -> None:
    """Append an interrupt entry to the artifacts directory."""
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


class AgyProvider(LLMProvider):
    """LLM provider that invokes the Antigravity CLI (`agy`)."""

    _pending_interrupt_message: str | None = None

    def resolve_model_name(self, model_tier: ModelTier = "large") -> str:
        """Return the Antigravity model name for the given tier."""
        return _TIER_TO_MODEL[model_tier]

    @hookimpl
    def llm_provider_name(self) -> str:
        return "agy"

    @hookimpl
    def llm_provider_short_name(self) -> str:
        return "agy"

    @hookimpl
    def llm_resolve_model_name(self, model_tier: ModelTier) -> str:
        return self.resolve_model_name(model_tier)

    @hookimpl
    def llm_known_model_names(self) -> list[str]:
        # Exact `agy models` display names (Antigravity CLI 1.0.10). These
        # contain spaces and parentheses and must be preserved verbatim.
        return [
            "Gemini 3.5 Flash (High)",
            "Gemini 3.5 Flash (Low)",
            "Gemini 3.5 Flash (Medium)",
            "Gemini 3.1 Pro (High)",
            "Gemini 3.1 Pro (Low)",
            "Claude Sonnet 4.6 (Thinking)",
            "Claude Opus 4.6 (Thinking)",
            "GPT-OSS 120B (Medium)",
        ]

    @hookimpl
    def llm_model_short_aliases(self) -> dict[str, str]:
        # Compact aliases for the space/paren-laden exact display names.
        return {
            "Gemini 3.5 Flash (High)": "flash35h",
            "Gemini 3.5 Flash (Low)": "flash35l",
            "Gemini 3.5 Flash (Medium)": "flash35m",
            "Gemini 3.1 Pro (High)": "pro31h",
            "Gemini 3.1 Pro (Low)": "pro31l",
            "Claude Sonnet 4.6 (Thinking)": "sonnet46t",
            "Claude Opus 4.6 (Thinking)": "opus46t",
            "GPT-OSS 120B (Medium)": "gptoss120m",
        }

    @hookimpl
    def llm_skill_template_context(self) -> dict[str, str]:
        return {
            "provider_name": "Antigravity",
            "provider_tool_name": "Antigravity CLI",
            "provider_native_ask_tool": "ask_user",
        }

    @hookimpl
    def llm_skill_deploy_subpath(self) -> str:
        return ".gemini/antigravity-cli"

    @hookimpl
    def llm_cli_status_color(self) -> str:
        # Distinct Antigravity indigo/violet — deliberately not Gemini blue.
        return "#6E5DE7"

    @hookimpl
    def llm_autodetect_priority(self) -> int:
        # Late fallback, inheriting the retired Gemini CLI slot.
        return 30

    @hookimpl
    def llm_autodetect_cli_name(self) -> str:
        return "agy"

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
        model_tier: ModelTier,
        suppress_output: bool = False,
        model_override: str | None = None,
    ) -> InvokeResult:
        """Invoke the Antigravity CLI with the given prompt.

        Args:
            prompt: The preprocessed prompt to send.
            model_tier: Which model tier to resolve when no override is given.
            suppress_output: If True, suppress real-time output to console.
            model_override: If set, use this model name directly.

        Returns:
            An ``InvokeResult`` with the response text. ``usage`` is ``None``
            because ``agy`` exposes no stable token accounting in print mode.

        Raises:
            subprocess.CalledProcessError: If the ``agy`` process fails.
            FileNotFoundError: If the ``agy`` executable cannot be launched.
        """
        model = model_override if model_override else _TIER_TO_MODEL[model_tier]

        base_args = [
            _agy_bin(),
            "--print-timeout",
            _agy_print_timeout(),
            "--model",
            model,
            "--dangerously-skip-permissions",
        ]

        if model_tier == "large":
            extra_args_env = os.environ.get(
                "SASE_LLM_LARGE_ARGS", os.environ.get("SASE_AGY_LARGE_ARGS")
            )
        else:
            extra_args_env = os.environ.get(
                "SASE_LLM_SMALL_ARGS", os.environ.get("SASE_AGY_SMALL_ARGS")
            )

        if extra_args_env:
            for arg in extra_args_env.split():
                base_args.append(arg)

        timer_context = (
            gemini_timer("Waiting for Antigravity") if not suppress_output else None
        )

        current_prompt = prompt
        accumulated_response = ""
        cycle = 0

        while True:
            # The prompt is the value of `--print`, so it must stay adjacent to
            # the flag and be rebuilt each interrupt cycle.
            command_args = [*base_args, "--print", current_prompt]
            if timer_context:
                with timer_context:
                    content, stderr_content, return_code = self._run_subprocess(
                        command_args, suppress_output
                    )
                    print()
            else:
                content, stderr_content, return_code = self._run_subprocess(
                    command_args, suppress_output
                )

            if self._pending_interrupt_message is not None:
                user_msg = self._pending_interrupt_message
                self._pending_interrupt_message = None
                cycle += 1
                _log_interrupt(user_msg, cycle)
                accumulated_response = (
                    accumulated_response + "\n\n" + content.strip()
                ).strip()
                # `agy --print` has no reliable print-mode session persistence,
                # so reconstruct context like the Qwen/OpenCode providers.
                current_prompt = (
                    f"{prompt}\n\n"
                    f"--- Work So Far ---\n{accumulated_response}\n\n"
                    f"--- User Message ---\n{user_msg}\n\n"
                    "Continue working, incorporating the user's message above."
                )
                continue

            if return_code != 0:
                raise subprocess.CalledProcessError(
                    return_code,
                    command_args,
                    output=content,
                    stderr=stderr_content,
                )

            accumulated_response = (
                accumulated_response + "\n\n" + content.strip()
            ).strip()
            return InvokeResult(content=accumulated_response, usage=None)

    def _run_subprocess(
        self,
        args: list[str],
        suppress_output: bool,
    ) -> tuple[str, str, int]:
        """Run the Antigravity CLI subprocess in plain-stdout streaming mode."""
        env = os.environ.copy()
        env["NO_COLOR"] = "1"
        env["TERM"] = "dumb"

        try:
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
        except FileNotFoundError as exc:
            raise _agy_executable_not_found_error(args[0]) from exc

        start_interrupt_monitor(
            process,
            on_interrupt=lambda msg: setattr(self, "_pending_interrupt_message", msg),
        )

        return stream_process_output(
            process, suppress_output=suppress_output, clean_ansi=True
        )
