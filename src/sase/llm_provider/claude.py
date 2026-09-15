"""Claude Code LLM provider implementation."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.output import provider_timer

from ._effort_args import effort_cli_args
from ._hookspec import hookimpl
from ._subprocess import start_interrupt_monitor, stream_and_parse_json_output
from ._subprocess_claude import ClaudeTurnWaitState
from .base import LLMProvider
from .types import InvokeResult, LLMInvocationError, LLMInvocationOptions, ModelTier

if TYPE_CHECKING:
    from .retry_config import ProviderRetryConfig
    from .usage.types import UsageProbeContext
    from .usage_limit_config import ProviderUsageLimitConfig

log = logging.getLogger(__name__)

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
_CLAUDE_MAX_WAIT_CONTINUATIONS_ENV = "SASE_CLAUDE_MAX_WAIT_CONTINUATIONS"
_DEFAULT_MAX_WAIT_CONTINUATIONS = 2
# Raise Claude Code's Bash tool timeout ceiling so long verification can stay
# in the foreground; commands still need explicit larger timeouts to use it.
_BASH_MAX_TIMEOUT_MS = "14400000"
_SINGLE_TURN_DIRECTIVE = (
    "SASE single-turn print mode: this session runs exactly one provider turn "
    "with no follow-up events. Background-task notifications, scheduled "
    "wake-ups, and 'you will be notified' promises can never reach you; "
    "anything still running when you give your final response is lost. Run "
    "commands synchronously in the foreground, and if a command is killed by "
    "its timeout, rerun it with a larger explicit timeout. Never end your "
    "turn to wait."
)
_WAIT_CONTINUATION_NUDGE = (
    "Your previous reply ended the turn waiting for a background notification "
    "or wake-up that will never arrive; this session is single-turn. Finish "
    "the work now: read the background task's output file directly or rerun "
    "the command synchronously in the foreground, then give your final answer. "
    "Do not end your turn waiting."
)
_WAIT_SIGNAL_RE = re.compile(
    r"\b(?:"
    r"i(?:'|\u2019)ll wait|"
    r"will be notified|"
    r"notify me|"
    r"when (?:it|the command|the task|the process) "
    r"(?:completes?|finishes?)|"
    r"waiting for|"
    r"still running|"
    r"in the background"
    r")\b",
    re.IGNORECASE,
)


def _claude_max_wait_continuations() -> int:
    """Return the bounded wait-state continuation budget."""
    raw_value = os.environ.get(_CLAUDE_MAX_WAIT_CONTINUATIONS_ENV)
    if raw_value is None:
        return _DEFAULT_MAX_WAIT_CONTINUATIONS
    try:
        return max(0, int(raw_value))
    except ValueError:
        return _DEFAULT_MAX_WAIT_CONTINUATIONS


def _join_response_parts(left: str, right: str) -> str:
    """Join non-empty response fragments using SASE's provider convention."""
    return (left + "\n\n" + right.strip()).strip()


def _classify_claude_wait_state(
    wait_state: ClaudeTurnWaitState,
) -> tuple[bool, str]:
    """Classify a completed Claude print-mode turn for impossible wait states."""
    if wait_state.schedule_wakeup_requested:
        return True, "schedule_wakeup_tool_use"

    if wait_state.outstanding_background_tasks:
        tail = wait_state.final_text_tail.strip()[-700:]
        if _WAIT_SIGNAL_RE.search(tail):
            task_ids = ",".join(sorted(wait_state.outstanding_background_tasks))
            return True, f"background_task_wait:{task_ids}"
        return False, "background_tasks_without_wait_reply"

    return False, "no_wait_state"


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
            "claude-haiku-4-5",
            "claude-fable-5",
        ]

    @hookimpl
    def llm_model_short_aliases(self) -> dict[str, str]:
        return {
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
            "vendor": "Anthropic",
            "docs_url": "https://code.claude.com/docs/en/installation",
            "self_update_argv": ["update"],
            "latest_version_package": "@anthropic-ai/claude-code",
            "brew_package": "claude-code",
        }

    @hookimpl
    def llm_interactive_cli(self) -> dict[str, object]:
        return {
            "menu_key": "c",
            "bypass_args": ["--dangerously-skip-permissions"],
            "model_args": ["--model", "{model}"],
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

    @hookimpl
    def llm_default_usage_limit_config(self) -> ProviderUsageLimitConfig:
        from .usage_limit_config import ProviderUsageLimitConfig

        # Anchored on Claude Code 2.1.235's own hard-limit classifier list
        # (``YZe`` / ``XOt`` / ``GEn``), not today's seven-day wording:
        # ``You've hit your <label>``, ``You've reached your``,
        # ``You're out of usage credits``, ``Your org is out of usage``,
        # plus the monthly spend/limit lines. Exact historical phrases are
        # kept so existing tests stay meaningful. ``exclude_patterns``
        # suppress the same binary's advisory/cooldown family, including
        # the fast-mode line ``You've hit your fast limit`` (the older
        # captured ``fast limit reached`` spelling is kept too).
        #
        # The binary's ``fW(epoch, withZone)`` formatter appends a
        # " · resets <X>" suffix that branches on distance from now. The
        # replace callback ``.replace(/ ([AP]M)/i, (_, mer) => mer.toLowerCase())``
        # returns only the lowercased meridiem, so it strips the space
        # ``toLocaleString`` inserted. Minutes of zero omit ``:00``.
        # Within 24h: ``resets 6:38pm (America/New_York)``. Beyond 24h —
        # which is what `seven_day` limits produce —
        # ``resets Aug 22, 8pm (America/New_York)`` (no space before the
        # meridiem; year inserted across a year boundary:
        # ``resets Aug 20, 2027, 8pm (...)``). A separate billing-error
        # body renders ``spend limit reached (monthly; resets 2026-08-20
        # 06:38 UTC)``. Both are parsed by usage_limit_config.py's
        # absolute-timestamp forms.
        return ProviderUsageLimitConfig(
            patterns=[
                "you've hit your usage limit",
                "you've hit your weekly limit",
                "you've hit your session limit",
                "you've hit your opus limit",
                "you've hit your sonnet limit",
                "usage limit reached",
                "claude usage limit reached",
                "you've hit your",
                "you've reached your",
                "you're out of usage credits",
                "your org is out of usage",
                "you've hit your monthly spend limit",
                "you've hit your monthly limit",
            ],
            exclude_patterns=[
                "usage limit approaching",
                "grace window active",
                "approaching your",
                "fast limit reached",
                "close to your usage limit",
                "you've hit your fast limit",
            ],
        )

    @hookimpl
    def llm_usage_capabilities(self) -> dict[str, object]:
        return {"probe": True, "passive_events": True}

    @hookimpl
    def llm_usage_probe(self, context: UsageProbeContext) -> dict[str, object] | None:
        from .usage.claude import collect_claude_usage

        return collect_claude_usage(context)

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
        active_session_uuid: str | None = None
        resume_session = False
        wait_continuations = 0
        max_wait_continuations = _claude_max_wait_continuations()
        while True:
            if active_session_uuid is None:
                active_session_uuid = str(uuid.uuid4())
            session_mode_arg = "--resume" if resume_session else "--session-id"
            base_args = [
                "claude",
                "-p",
                "--verbose",
                "--model",
                model_alias,
                "--output-format",
                "stream-json",
                "--dangerously-skip-permissions",
                "--append-system-prompt",
                _SINGLE_TURN_DIRECTIVE,
                "--disallowedTools",
                "ScheduleWakeup",
                session_mode_arg,
                active_session_uuid,
            ]

            base_args.extend(effort_args)

            if extra_args_env:
                for arg in extra_args_env.split():
                    base_args.append(arg)

            wait_state = ClaudeTurnWaitState()
            if timer_context:
                with timer_context:
                    content, stderr_content, return_code, usage = self._run_subprocess(
                        base_args,
                        current_prompt,
                        suppress_output,
                        wait_state=wait_state,
                    )
                    print()
            else:
                content, stderr_content, return_code, usage = self._run_subprocess(
                    base_args,
                    current_prompt,
                    suppress_output,
                    wait_state=wait_state,
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
                response_content = _join_response_parts(response_content, content)
                current_prompt = user_msg
                active_session_uuid = None
                resume_session = False
                continue

            if return_code != 0:
                raise subprocess.CalledProcessError(
                    return_code,
                    base_args,
                    output=content,
                    stderr=stderr_content,
                )

            response_content = _join_response_parts(response_content, content)
            is_wait_state, wait_reason = _classify_claude_wait_state(wait_state)
            if is_wait_state:
                if wait_continuations >= max_wait_continuations:
                    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
                    artifact_hint = (
                        f" Artifacts: {artifacts_dir}." if artifacts_dir else ""
                    )
                    raise LLMInvocationError(
                        "Claude produced a wait-for-background reply after "
                        f"{wait_continuations} continuation(s); refusing to "
                        "report it as success. Reason: "
                        f"{wait_reason}. The model is waiting on a notification "
                        f"that `claude -p` cannot deliver.{artifact_hint}"
                    )
                wait_continuations += 1
                current_prompt = _WAIT_CONTINUATION_NUDGE
                resume_session = True
                continue

            return InvokeResult(content=response_content.strip(), usage=total_usage)

    def _run_subprocess(
        self,
        args: list[str],
        prompt: str,
        suppress_output: bool,
        *,
        wait_state: ClaudeTurnWaitState | None = None,
    ) -> tuple[str, str, int, dict[str, int]]:
        """Run the Claude CLI subprocess.

        Args:
            args: Command-line arguments.
            prompt: Prompt to write to stdin.
            suppress_output: If True, suppress output.

        Returns:
            Tuple of (stdout_content, stderr_content, return_code, usage_totals).
        """
        from .usage.claude import capture_claude_passive_usage_context

        try:
            usage_context = capture_claude_passive_usage_context(executable=args[0])
        except Exception:  # noqa: BLE001 - never let usage capture break invoke.
            log.debug("Claude passive usage context capture failed", exc_info=True)
            usage_context = None
        env = os.environ.copy()
        env.setdefault("CLAUDE_CODE_DISABLE_BACKGROUND_TASKS", "1")
        env.setdefault("BASH_MAX_TIMEOUT_MS", _BASH_MAX_TIMEOUT_MS)

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

        # Stream JSON output and extract assistant text
        return stream_and_parse_json_output(
            process,
            suppress_output=suppress_output,
            usage_context=usage_context,
            wait_state=wait_state,
        )
