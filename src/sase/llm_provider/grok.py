"""xAI Grok Build (`grok`) LLM provider implementation."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.output import provider_timer

from ._effort_args import effort_cli_args
from ._hookspec import hookimpl
from ._subprocess import (
    start_interrupt_monitor,
    stream_and_parse_messages_json_output,
)
from ._tool_calls import append_grok_tool_call_event
from .base import LLMProvider
from .types import InvokeResult, LLMInvocationOptions, ModelTier

if TYPE_CHECKING:
    from .retry_config import ProviderRetryConfig

_TIER_TO_MODEL: dict[ModelTier, str] = {
    "large": "grok-4.6",
    "small": "grok-4.6",
}

_EFFORT_CLI_ARGS: dict[str, list[str]] = {
    level: ["--effort", level] for level in ("low", "medium", "high", "xhigh")
}

_GROK_PATH_ENV = "SASE_GROK_PATH"
_GROK_CLI_NAME = "grok"


def _resolve_grok_executable() -> str:
    """Return the Grok Build executable SASE should launch."""
    explicit_path = os.environ.get(_GROK_PATH_ENV)
    if explicit_path:
        return explicit_path

    path_result = shutil.which(_GROK_CLI_NAME)
    if path_result:
        return path_result

    return _GROK_CLI_NAME


def _grok_executable_not_found_error(command: str) -> FileNotFoundError:
    """Build an actionable missing-Grok diagnostic."""
    return FileNotFoundError(
        "Unable to launch Grok Build executable "
        f"{command!r}. Set SASE_GROK_PATH to the Grok Build binary, ensure "
        "'grok' is discoverable on PATH, or run `sase agent-cli install grok`. "
        "If PATH resolves to grok-dev or Homebrew's deprecated regex tool, "
        "point SASE_GROK_PATH at the @xai-official/grok binary."
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


class GrokProvider(LLMProvider):
    """LLM provider that invokes xAI's Grok Build CLI."""

    _pending_interrupt_message: str | None = None

    def resolve_model_name(self, model_tier: ModelTier = "large") -> str:
        """Return the Grok model name for the given tier."""
        return _TIER_TO_MODEL[model_tier]

    @hookimpl
    def llm_provider_name(self) -> str:
        return "grok"

    @hookimpl
    def llm_provider_short_name(self) -> str:
        return "grk"

    @hookimpl
    def llm_resolve_model_name(self, model_tier: ModelTier) -> str:
        return self.resolve_model_name(model_tier)

    @hookimpl
    def llm_known_model_names(self) -> list[str]:
        return ["grok-4.6"]

    @hookimpl
    def llm_skill_template_context(self) -> dict[str, str]:
        return {
            "provider_name": "Grok",
            "provider_tool_name": "Grok Build",
            "provider_native_ask_tool": "ask_user_question",
        }

    @hookimpl
    def llm_cli_status_color(self) -> str:
        return "#00C8D7"

    @hookimpl
    def llm_autodetect_cli_name(self) -> str:
        return _GROK_CLI_NAME

    @hookimpl
    def llm_auth_evidence(self) -> dict[str, list[str]]:
        return {
            "credential_paths": ["~/.grok/auth.json"],
            "api_key_env_vars": ["XAI_API_KEY"],
        }

    @hookimpl
    def llm_install_metadata(self) -> dict[str, object]:
        # @xai-official/grok is an npm trampoline: `npm install -g` places a
        # shim on PATH, but the real Grok Build binary it downloads on first
        # run lives under ~/.grok/bin/, not node_modules.
        return {
            "manager": "npm",
            "package": "@xai-official/grok",
            "scope": "global",
            "display_name": "Grok Build",
            "docs_url": "https://docs.x.ai/build/overview",
            "self_update_argv": ["update"],
            "latest_version_package": "@xai-official/grok",
        }

    @hookimpl
    def llm_default_retry_config(self) -> ProviderRetryConfig:
        from .retry_config import (
            _RETRY_CONTINUATION_NUDGE,
            ProviderRetryConfig,
        )

        return ProviderRetryConfig(
            max_retries=3,
            error_patterns=[
                "xAI API error",
                "xAI rate limit",
                "xAI server error",
                "xAI upstream request failed",
            ],
            wait_times=[60, 300, 1800],
            continuation_prompt=_RETRY_CONTINUATION_NUDGE,
            preserve_workspace=True,
        )

    def invocation_option_args(self, options: LLMInvocationOptions | None) -> list[str]:
        """Translate a resolved reasoning effort into ``--effort`` args."""
        return effort_cli_args(
            options, provider_label="Grok Build", supported=_EFFORT_CLI_ARGS
        )

    @hookimpl
    def llm_invoke(
        self,
        prompt: str,
        model_tier: ModelTier,
        suppress_output: bool,
        model_override: str | None,
        options: LLMInvocationOptions | None,
    ) -> InvokeResult:
        return self.invoke(
            prompt,
            model_tier=model_tier,
            suppress_output=suppress_output,
            model_override=model_override,
            options=options,
        )

    def invoke(
        self,
        prompt: str,
        *,
        model_tier: ModelTier,
        suppress_output: bool = False,
        model_override: str | None = None,
        options: LLMInvocationOptions | None = None,
    ) -> InvokeResult:
        """Invoke Grok Build with the given prompt."""
        model = model_override if model_override else _TIER_TO_MODEL[model_tier]
        effort_args = self.invocation_option_args(options)

        if model_tier == "large":
            extra_args_env = os.environ.get(
                "SASE_LLM_LARGE_ARGS", os.environ.get("SASE_GROK_LARGE_ARGS")
            )
        else:
            extra_args_env = os.environ.get(
                "SASE_LLM_SMALL_ARGS", os.environ.get("SASE_GROK_SMALL_ARGS")
            )

        timer_context = (
            provider_timer("Waiting for Grok") if not suppress_output else None
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

        return self._invoke_loop(
            current_prompt=current_prompt,
            original_prompt=prompt,
            accumulated_response=accumulated_response,
            total_usage=total_usage,
            cycle=cycle,
            model=model,
            effort_args=effort_args,
            extra_args_env=extra_args_env,
            timer_context=timer_context,
            suppress_output=suppress_output,
        )

    def _invoke_loop(
        self,
        *,
        current_prompt: str,
        original_prompt: str,
        accumulated_response: str,
        total_usage: dict[str, int],
        cycle: int,
        model: str,
        effort_args: list[str],
        extra_args_env: str | None,
        timer_context: Any,
        suppress_output: bool,
    ) -> InvokeResult:
        while True:
            command_args = [
                _resolve_grok_executable(),
                "--prompt-file",
                "/dev/stdin",
                "--output-format",
                "streaming-messages-json",
                "--permission-mode",
                "bypassPermissions",
                "--model",
                model,
                "--cwd",
                os.getcwd(),
                "--session-id",
                str(uuid.uuid4()),
                "--no-plan",
                "--no-ask-user",
                "--no-auto-update",
                "--no-leader",
                *effort_args,
            ]

            if extra_args_env:
                for arg in extra_args_env.split():
                    command_args.append(arg)

            if timer_context:
                with timer_context:
                    content, stderr_content, return_code, usage = self._run_subprocess(
                        command_args, current_prompt, suppress_output
                    )
                    print()
            else:
                content, stderr_content, return_code, usage = self._run_subprocess(
                    command_args, current_prompt, suppress_output
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
                    f"{original_prompt}\n\n"
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
        prompt: str,
        suppress_output: bool,
    ) -> tuple[str, str, int, dict[str, int]]:
        """Run the Grok Build subprocess and parse its Messages JSON stream."""
        try:
            process = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError as exc:
            raise _grok_executable_not_found_error(args[0]) from exc

        if process.stdin:
            process.stdin.write(prompt)
            process.stdin.close()

        start_interrupt_monitor(
            process,
            on_interrupt=lambda msg: setattr(self, "_pending_interrupt_message", msg),
        )

        return stream_and_parse_messages_json_output(
            process,
            suppress_output=suppress_output,
            runtime="grok",
            tool_call_writer=append_grok_tool_call_event,
            thinking_sink=True,
        )
