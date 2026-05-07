"""OpenCode LLM provider implementation."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from sase.output import gemini_timer

from ._hookspec import hookimpl
from ._subprocess import start_interrupt_monitor, stream_and_parse_opencode_json_output
from .base import LLMProvider
from .types import InvokeResult, ModelTier

_TIER_TO_MODEL: dict[ModelTier, str] = {
    "large": "anthropic/claude-sonnet-4-5",
    "small": "openai/gpt-5-mini",
}
_OPENCODE_PATH_ENV = "SASE_OPENCODE_PATH"


def _opencode_bin() -> str:
    """Return the OpenCode executable SASE should launch."""
    return os.environ.get(_OPENCODE_PATH_ENV, "opencode")


def _opencode_executable_not_found_error(command: str) -> FileNotFoundError:
    """Build an actionable missing-OpenCode diagnostic."""
    return FileNotFoundError(
        "Unable to launch OpenCode executable "
        f"{command!r}. Set SASE_OPENCODE_PATH to the OpenCode binary or ensure "
        "'opencode' is discoverable on PATH."
    )


def _log_interrupt(message: str | None, cycle: int) -> None:
    """Append an interrupt entry to the artifacts directory."""
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


class OpenCodeProvider(LLMProvider):
    """LLM provider that invokes the OpenCode CLI tool."""

    _pending_interrupt_message: str | None = None

    def resolve_model_name(self, model_tier: ModelTier = "large") -> str:
        """Return the OpenCode model name for the given tier."""
        return _TIER_TO_MODEL[model_tier]

    @hookimpl
    def llm_provider_name(self) -> str:
        return "opencode"

    @hookimpl
    def llm_provider_short_name(self) -> str:
        return "opc"

    @hookimpl
    def llm_resolve_model_name(self, model_tier: ModelTier) -> str:
        return self.resolve_model_name(model_tier)

    @hookimpl
    def llm_known_model_names(self) -> list[str]:
        return [
            "anthropic/claude-sonnet-4-5",
            "anthropic/claude-opus-4-5",
            "openai/gpt-5",
            "openai/gpt-5-mini",
            "google/gemini-3-flash-preview",
            "qwen/qwen3-coder-plus",
        ]

    @hookimpl
    def llm_model_short_aliases(self) -> dict[str, str]:
        return {
            "anthropic/claude-sonnet-4-5": "sonnet45",
            "anthropic/claude-opus-4-5": "opus45",
            "openai/gpt-5": "gpt5",
            "openai/gpt-5-mini": "gpt5m",
            "google/gemini-3-flash-preview": "flash3",
            "qwen/qwen3-coder-plus": "qwen3cp",
        }

    @hookimpl
    def llm_skill_template_context(self) -> dict[str, str]:
        return {
            "provider_name": "OpenCode",
            "provider_tool_name": "OpenCode",
            "provider_native_ask_tool": "ask_user",
        }

    @hookimpl
    def llm_skill_deploy_subpath(self) -> str:
        return ".config/opencode"

    @hookimpl
    def llm_cli_status_color(self) -> str:
        return "#FFB454"

    @hookimpl
    def llm_autodetect_priority(self) -> int:
        return 18

    @hookimpl
    def llm_autodetect_cli_name(self) -> str:
        return "opencode"

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
        """Invoke OpenCode with the given prompt."""
        model = model_override if model_override else _TIER_TO_MODEL[model_tier]

        base_args = [
            _opencode_bin(),
            "run",
            "--format",
            "json",
            "--dangerously-skip-permissions",
            "--model",
            model,
            "--dir",
            os.getcwd(),
        ]

        if model_tier == "large":
            extra_args_env = os.environ.get(
                "SASE_LLM_LARGE_ARGS", os.environ.get("SASE_OPENCODE_LARGE_ARGS")
            )
        else:
            extra_args_env = os.environ.get(
                "SASE_LLM_SMALL_ARGS", os.environ.get("SASE_OPENCODE_SMALL_ARGS")
            )

        if extra_args_env:
            for arg in extra_args_env.split():
                base_args.append(arg)

        timer_context = (
            gemini_timer("Waiting for OpenCode") if not suppress_output else None
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
            command_args = [*base_args, current_prompt]
            if timer_context:
                with timer_context:
                    content, stderr_content, return_code, usage = self._run_subprocess(
                        command_args, suppress_output
                    )
                    print()
            else:
                content, stderr_content, return_code, usage = self._run_subprocess(
                    command_args, suppress_output
                )

            for key in total_usage:
                total_usage[key] += usage.get(key, 0)

            if self._pending_interrupt_message is not None:
                user_msg = self._pending_interrupt_message
                self._pending_interrupt_message = None
                cycle += 1
                _log_interrupt(user_msg, cycle)
                accumulated_response = (
                    accumulated_response + "\n\n" + content.strip()
                ).strip()
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
            return InvokeResult(content=accumulated_response, usage=total_usage)

    def _run_subprocess(
        self,
        args: list[str],
        suppress_output: bool,
    ) -> tuple[str, str, int, dict[str, int]]:
        """Run the OpenCode subprocess."""
        try:
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError as exc:
            raise _opencode_executable_not_found_error(args[0]) from exc

        start_interrupt_monitor(
            process,
            on_interrupt=lambda msg: setattr(self, "_pending_interrupt_message", msg),
        )

        return stream_and_parse_opencode_json_output(
            process, suppress_output=suppress_output
        )
