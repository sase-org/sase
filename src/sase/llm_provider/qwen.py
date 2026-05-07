"""Qwen Code LLM provider implementation."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from sase.output import gemini_timer

from ._hookspec import hookimpl
from ._subprocess import start_interrupt_monitor, stream_and_parse_qwen_json_output
from .base import LLMProvider
from .types import InvokeResult, ModelTier

_TIER_TO_MODEL: dict[ModelTier, str] = {
    "large": "qwen3-coder-plus",
    "small": "qwen3-coder-flash",
}
_QWEN_PATH_ENV = "SASE_QWEN_PATH"


def _qwen_bin() -> str:
    """Return the Qwen Code executable SASE should launch."""
    return os.environ.get(_QWEN_PATH_ENV, "qwen")


def _qwen_executable_not_found_error(command: str) -> FileNotFoundError:
    """Build an actionable missing-Qwen diagnostic."""
    return FileNotFoundError(
        "Unable to launch Qwen Code executable "
        f"{command!r}. Set SASE_QWEN_PATH to the Qwen Code binary or ensure "
        "'qwen' is discoverable on PATH."
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


class QwenProvider(LLMProvider):
    """LLM provider that invokes the Qwen Code CLI tool."""

    _pending_interrupt_message: str | None = None

    def resolve_model_name(self, model_tier: ModelTier = "large") -> str:
        """Return the Qwen model name for the given tier."""
        return _TIER_TO_MODEL[model_tier]

    @hookimpl
    def llm_provider_name(self) -> str:
        return "qwen"

    @hookimpl
    def llm_provider_short_name(self) -> str:
        return "qwn"

    @hookimpl
    def llm_resolve_model_name(self, model_tier: ModelTier) -> str:
        return self.resolve_model_name(model_tier)

    @hookimpl
    def llm_known_model_names(self) -> list[str]:
        return [
            "qwen3-coder-plus",
            "qwen3-coder-flash",
            "qwen3-max",
            "qwen-plus",
            "qwen-max",
        ]

    @hookimpl
    def llm_model_short_aliases(self) -> dict[str, str]:
        return {
            "qwen3-coder-plus": "qwen3cp",
            "qwen3-coder-flash": "qwen3cf",
        }

    @hookimpl
    def llm_skill_template_context(self) -> dict[str, str]:
        return {
            "provider_name": "Qwen",
            "provider_tool_name": "Qwen Code",
            "provider_native_ask_tool": "ask_user",
        }

    @hookimpl
    def llm_skill_deploy_subpath(self) -> str:
        return ".qwen"

    @hookimpl
    def llm_cli_status_color(self) -> str:
        return "#7CFF6B"

    @hookimpl
    def llm_autodetect_priority(self) -> int:
        return 15

    @hookimpl
    def llm_autodetect_cli_name(self) -> str:
        return "qwen"

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
        """Invoke Qwen Code with the given prompt."""
        model = model_override if model_override else _TIER_TO_MODEL[model_tier]

        base_args = [
            _qwen_bin(),
            "--input-format",
            "text",
            "--output-format",
            "stream-json",
            "--yolo",
            "--model",
            model,
        ]

        if model_tier == "large":
            extra_args_env = os.environ.get(
                "SASE_LLM_LARGE_ARGS", os.environ.get("SASE_QWEN_LARGE_ARGS")
            )
        else:
            extra_args_env = os.environ.get(
                "SASE_LLM_SMALL_ARGS", os.environ.get("SASE_QWEN_SMALL_ARGS")
            )

        if extra_args_env:
            for arg in extra_args_env.split():
                base_args.append(arg)

        timer_context = (
            gemini_timer("Waiting for Qwen") if not suppress_output else None
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
                    content, stderr_content, return_code, usage = self._run_subprocess(
                        base_args, current_prompt, suppress_output
                    )
                    print()
            else:
                content, stderr_content, return_code, usage = self._run_subprocess(
                    base_args, current_prompt, suppress_output
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
                    base_args,
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
        prompt: str,
        suppress_output: bool,
    ) -> tuple[str, str, int, dict[str, int]]:
        """Run the Qwen Code subprocess."""
        try:
            process = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError as exc:
            raise _qwen_executable_not_found_error(args[0]) from exc

        if process.stdin:
            process.stdin.write(prompt)
            process.stdin.close()

        start_interrupt_monitor(
            process,
            on_interrupt=lambda msg: setattr(self, "_pending_interrupt_message", msg),
        )

        return stream_and_parse_qwen_json_output(
            process, suppress_output=suppress_output
        )
