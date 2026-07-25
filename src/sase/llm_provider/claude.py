"""Claude Code LLM provider implementation."""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.output import provider_timer

from ._effort_args import effort_cli_args
from ._hookspec import hookimpl
from ._subprocess import start_interrupt_monitor, stream_and_parse_json_output
from .base import LLMProvider
from .types import InvokeResult, LLMInvocationOptions, ModelTier

if TYPE_CHECKING:
    from .retry_config import ProviderRetryConfig

# Map model tiers to Claude CLI aliases
_TIER_TO_MODEL: dict[ModelTier, str] = {
    "large": "opus",
    "small": "sonnet",
}

# Reasoning-effort levels Claude Code honors via ``--effort <level>``. Claude
# rejects ``none``/``minimal`` (epic sase-55 provider support matrix).
_EFFORT_CLI_ARGS: dict[str, list[str]] = {
    level: ["--effort", level] for level in ("low", "medium", "high", "xhigh", "max")
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

    @hookimpl
    def llm_provider_name(self) -> str:
        return "claude"

    @hookimpl
    def llm_provider_short_name(self) -> str:
        return "cld"

    @hookimpl
    def llm_resolve_model_name(self, model_tier: ModelTier) -> str:
        return self.resolve_model_name(model_tier)

    @hookimpl
    def llm_known_model_names(self) -> list[str]:
        return [
            "opus",
            "sonnet",
            "haiku",
            "claude-opus-5",
            "claude-sonnet-5",
            "claude-haiku-4-5",
            "claude-fable-5",
        ]

    @hookimpl
    def llm_model_short_aliases(self) -> dict[str, str]:
        return {
            "claude-opus-5": "opus5",
            "claude-sonnet-5": "sonnet5",
            "claude-haiku-4-5": "haiku45",
            "claude-fable-5": "fable",
        }

    @hookimpl
    def llm_skill_template_context(self) -> dict[str, str]:
        return {
            "provider_name": "Claude",
            "provider_tool_name": "Claude Code",
            "provider_native_ask_tool": "AskUserQuestion",
        }

    @hookimpl
    def llm_autodetect_priority(self) -> int:
        return 0

    @hookimpl
    def llm_autodetect_cli_name(self) -> str:
        return "claude"

    @hookimpl
    def llm_auth_evidence(self) -> dict[str, list[str]]:
        return {
            "credential_paths": ["~/.claude/.credentials.json"],
            "api_key_env_vars": [
                "ANTHROPIC_API_KEY",
                "ANTHROPIC_AUTH_TOKEN",
                "CLAUDE_CODE_OAUTH_TOKEN",
            ],
        }

    @hookimpl
    def llm_install_metadata(self) -> dict[str, object]:
        return {
            "manager": "npm",
            "package": "@anthropic-ai/claude-code",
            "scope": "global",
            "display_name": "Claude Code",
            "docs_url": "https://code.claude.com/docs/en/installation",
            "self_update_argv": ["update"],
            "latest_version_package": "@anthropic-ai/claude-code",
            "brew_package": "claude-code",
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
                "Prompt is too long",
                "socket connection was closed unexpectedly",
                "API Error",
            ],
            wait_times=[0],
            continuation_prompt=_RETRY_CONTINUATION_NUDGE,
            preserve_workspace=True,
        )

    def invocation_option_args(self, options: LLMInvocationOptions | None) -> list[str]:
        """Translate a resolved reasoning effort into ``--effort`` args."""
        return effort_cli_args(
            options, provider_label="Claude", supported=_EFFORT_CLI_ARGS
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
        """Invoke Claude Code CLI with the given prompt.

        Args:
            prompt: The preprocessed prompt to send.
            model_tier: Which model tier to use ("large" or "small").
            suppress_output: If True, suppress real-time output to console.
            model_override: If set, use this model name directly instead of
                mapping from ``model_tier``.
            options: Resolved per-invocation options; the reasoning effort is
                translated into ``--effort`` args.

        Returns:
            An ``InvokeResult`` with the response text and token usage.

        Raises:
            subprocess.CalledProcessError: If the Claude CLI process fails.
        """
        model_alias = model_override if model_override else _TIER_TO_MODEL[model_tier]
        effort_args = self.invocation_option_args(options)

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
            provider_timer("Waiting for Claude") if not suppress_output else None
        )

        current_prompt = prompt
        response_content = ""
        total_usage: dict[str, int] = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
        cycle = 0

        return self._invoke_loop(
            current_prompt=current_prompt,
            response_content=response_content,
            total_usage=total_usage,
            cycle=cycle,
            model_alias=model_alias,
            effort_args=effort_args,
            extra_args_env=extra_args_env,
            timer_context=timer_context,
            suppress_output=suppress_output,
        )

    def _invoke_loop(
        self,
        *,
        current_prompt: str,
        response_content: str,
        total_usage: dict[str, int],
        cycle: int,
        model_alias: str,
        effort_args: list[str],
        extra_args_env: str | None,
        timer_context: Any,
        suppress_output: bool,
    ) -> InvokeResult:
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

            base_args.extend(effort_args)

            if extra_args_env:
                for arg in extra_args_env.split():
                    base_args.append(arg)

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
            return InvokeResult(content=response_content.strip(), usage=total_usage)

    def _run_subprocess(
        self,
        args: list[str],
        prompt: str,
        suppress_output: bool,
    ) -> tuple[str, str, int, dict[str, int]]:
        """Run the Claude CLI subprocess.

        Args:
            args: Command-line arguments.
            prompt: Prompt to write to stdin.
            suppress_output: If True, suppress output.

        Returns:
            Tuple of (stdout_content, stderr_content, return_code, usage_totals).
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

        start_interrupt_monitor(
            process,
            on_interrupt=lambda msg: setattr(self, "_pending_interrupt_message", msg),
        )

        # Stream JSON output and extract assistant text
        return stream_and_parse_json_output(process, suppress_output=suppress_output)
