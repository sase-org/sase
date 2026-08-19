"""Antigravity (`agy`) LLM provider implementation.

This is the MVP plain-stdout provider for Google's Antigravity CLI (`agy`),
the replacement for the retired consumer Gemini CLI. The Antigravity CLI does
not currently document a machine-readable JSON/stream output mode, so this
provider streams plain stdout through the shared
:func:`stream_process_output` helper and returns ``usage=None``. Tool-call,
usage, and thinking artifacts are intentionally unsupported from stdout. A
guarded post-run extractor may populate tool-call rows from Antigravity's local
trajectory DB for explicitly supported CLI versions.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

from sase.env_contracts import WORKSPACE_PIN_ENV_VARS
from sase.output import provider_timer

from ._effort_args import effort_cli_args
from ._hookspec import hookimpl
from ._subprocess import start_interrupt_monitor, stream_process_output
from ._subprocess_agy import (
    AgyTurnProgress,
    analyze_agy_turn_progress,
    append_agy_tool_call_events,
    prepare_agy_tool_call_extraction,
)
from .base import LLMProvider
from .types import (
    InvokeResult,
    LLMInvocationError,
    LLMInvocationOptions,
    ModelTier,
)

if TYPE_CHECKING:
    from .retry_config import ProviderRetryConfig
    from .usage_limit_config import ProviderUsageLimitConfig

_TIER_TO_MODEL: dict[ModelTier, str] = {
    "large": "gemini-3.7-flash-high",
    "small": "gemini-3.7-flash-low",
}
_AGY_PATH_ENV = "SASE_AGY_PATH"
_AGY_PRINT_TIMEOUT_ENV = "SASE_AGY_PRINT_TIMEOUT"
_AGY_MAX_NO_PROGRESS_CONTINUATIONS_ENV = "SASE_AGY_MAX_NO_PROGRESS_CONTINUATIONS"
# Antigravity's built-in `--print-timeout` default is 5m, which is far too
# short for long agentic SASE runs. Default to a generous, overridable window;
# the value is a Go duration string as accepted by `agy --print-timeout`.
_DEFAULT_PRINT_TIMEOUT = "24h"
_DEFAULT_MAX_NO_PROGRESS_CONTINUATIONS = 2
# Linux rejects a single argv element above 128 KiB. Keep SASE's guard below
# that so `agy --print <prompt>` fails with an actionable error before exec.
_AGY_PRINT_PROMPT_ARGV_BYTE_LIMIT = 120 * 1024
_AGY_WORKSPACE_ENV_VARS = WORKSPACE_PIN_ENV_VARS
_AGY_PRINT_MODE_DIRECTIVE = """SASE Antigravity print-mode instructions:
- You are running non-interactively with --dangerously-skip-permissions; never ask the user to approve commands or tool calls.
- Run commands synchronously and wait for their output. Do not start background or async tasks; print mode has no follow-up event loop to receive notifications.
- Do not end with only a plan, "I will", "waiting", "pausing", or "will be notified" message. Use your tools now and complete the task.
- Put the final user-facing answer directly in stdout."""
_NO_PROGRESS_CONTINUATION_NUDGE = (
    "You described a plan or a wait state but did not carry the task through. "
    "Do not restate the plan. Run your tools synchronously now to execute each "
    "step, then output the final answer directly."
)
_NO_PROGRESS_INTENTION_LINE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?"
    r"(?:next,\s*)?"
    r"(?:i will|i'll|i am going to|i'm going to|let me|i need to|i plan to)\b",
    re.IGNORECASE,
)
_NO_PROGRESS_FUTURE_RE = re.compile(
    r"\b(?:i will|i'll|i am going to|i'm going to|let me|i need to|i plan to)\b",
    re.IGNORECASE,
)
_NO_PROGRESS_WAIT_RE = re.compile(
    r"\b(?:wait(?:ing)?|paus(?:e|ing)|please approve|approve the command|"
    r"will be notified|notify me|background(?:ed)?|async task|"
    r"command execution to complete|stop calling tools)\b",
    re.IGNORECASE,
)
_NO_PROGRESS_COMPLETION_RE = re.compile(
    r"\b(?:implemented|fixed|updated|created|wrote|verified|completed|done)\b"
    r"|(?:^|\n)\s*(?:summary|recommendation|findings|result)s?:"
    r"|\bi recommend\b"
    r"|\btests?:\s*(?:pass|passed|not run)",
    re.IGNORECASE,
)


def _agy_bin() -> str:
    """Return the Antigravity CLI executable SASE should launch."""
    return os.environ.get(_AGY_PATH_ENV, "agy")


def _agy_print_timeout() -> str:
    """Return the `agy --print-timeout` duration (Go duration string)."""
    return os.environ.get(_AGY_PRINT_TIMEOUT_ENV, _DEFAULT_PRINT_TIMEOUT)


def _agy_max_no_progress_continuations() -> int:
    """Return the bounded no-progress continuation budget."""
    raw_value = os.environ.get(_AGY_MAX_NO_PROGRESS_CONTINUATIONS_ENV)
    if raw_value is None:
        return _DEFAULT_MAX_NO_PROGRESS_CONTINUATIONS
    try:
        return max(0, int(raw_value))
    except ValueError:
        return _DEFAULT_MAX_NO_PROGRESS_CONTINUATIONS


def _resolve_agy_workspace_dir() -> str:
    """Resolve the workspace Antigravity should be pinned to."""
    for env_name in _AGY_WORKSPACE_ENV_VARS:
        value = os.environ.get(env_name)
        if value:
            candidate = Path(value).expanduser().resolve(strict=False)
            if candidate.is_dir():
                return str(candidate)
    return str(Path.cwd().resolve())


def _agy_executable_not_found_error(command: str) -> FileNotFoundError:
    """Build an actionable missing-Antigravity diagnostic."""
    return FileNotFoundError(
        "Unable to launch Antigravity CLI executable "
        f"{command!r}. Set SASE_AGY_PATH to the Antigravity (`agy`) binary or "
        "ensure 'agy' is discoverable on PATH."
    )


def _agy_workspace_dir_not_found_error(cwd: str) -> FileNotFoundError:
    """Build an actionable missing-workspace diagnostic."""
    return FileNotFoundError(
        "Unable to launch Antigravity CLI from workspace directory "
        f"{cwd!r} because it does not exist. Clear stale workspace environment "
        "variables such as CODEX_PROJECT_DIR or SASE_ACTIVE_PROJECT_DIR, or "
        "start the provider from an existing workspace."
    )


def _validate_print_prompt_argv_transport(prompt: str) -> None:
    """Reject prompts too large for Antigravity's current argv transport."""
    prompt_bytes = len(prompt.encode("utf-8"))
    if prompt_bytes <= _AGY_PRINT_PROMPT_ARGV_BYTE_LIMIT:
        return

    raise LLMInvocationError(
        "Antigravity (`agy`) prompt is too large for SASE's argv transport: "
        f"{prompt_bytes} UTF-8 bytes exceeds the "
        f"{_AGY_PRINT_PROMPT_ARGV_BYTE_LIMIT}-byte guard. The current "
        "Antigravity CLI requires `agy --print` prompts to be sent as one "
        "argv element; it does not document a stable stdin/prompt-file "
        "contract that SASE can use as a fallback. Reduce the prompt size or "
        "use a stdin-capable provider until upstream adds a non-argv prompt "
        "transport."
    )


def _wrap_agy_print_prompt(prompt: str) -> str:
    """Wrap the user prompt with Antigravity print-mode safety guidance."""
    return f"{_AGY_PRINT_MODE_DIRECTIVE}\n\n--- User Prompt ---\n{prompt}"


def _build_no_progress_continuation_prompt(
    original_prompt: str,
    work_so_far: str,
) -> str:
    """Build the accumulated-context restart prompt for no-progress recovery."""
    previous = work_so_far.strip() or "(none)"
    return (
        f"{original_prompt}\n\n"
        f"--- Work So Far ---\n{previous}\n\n"
        f"--- Required Continuation ---\n{_NO_PROGRESS_CONTINUATION_NUDGE}"
    )


def _join_response_parts(left: str, right: str) -> str:
    """Join non-empty response fragments using SASE's provider convention."""
    return (left + "\n\n" + right.strip()).strip()


def _classify_agy_no_progress(
    content: str,
    structural_progress: AgyTurnProgress | None,
) -> tuple[bool, str]:
    """Classify whether one ``agy --print`` turn should be accepted."""
    if not content.strip():
        return True, "empty_stdout"

    if structural_progress is not None:
        if structural_progress.no_progress:
            return True, structural_progress.reason
        return False, structural_progress.reason

    if _looks_like_no_progress(content):
        return True, "planning_only_text"
    return False, "text_progress"


def _looks_like_no_progress(content: str) -> bool:
    """Conservative text fallback for planning-only/waiting ``agy`` replies."""
    stripped = content.strip()
    if not stripped:
        return True

    tail = stripped[-700:]
    has_wait_signal = bool(_NO_PROGRESS_WAIT_RE.search(tail))
    if _NO_PROGRESS_COMPLETION_RE.search(stripped) and not has_wait_signal:
        return False

    lines = [line for line in stripped.splitlines() if line.strip()]
    if not lines:
        return True

    intention_lines = sum(
        1 for line in lines if _NO_PROGRESS_INTENTION_LINE_RE.search(line)
    )
    future_mentions = len(_NO_PROGRESS_FUTURE_RE.findall(stripped))
    word_count = len(re.findall(r"\w+", stripped))
    dominated_by_intentions = (
        future_mentions >= 2 or intention_lines / max(1, len(lines)) >= 0.5
    )
    low_substance = word_count < 70

    return dominated_by_intentions and (has_wait_signal or low_substance)


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
        # Exact stable slugs reported by `agy models`; keep CLI ordering.
        return [
            "gemini-3.7-flash-high",
            "gemini-3.7-flash-medium",
            "gemini-3.7-flash-low",
            "gemini-3.6-flash-high",
            "gemini-3.6-flash-medium",
            "gemini-3.6-flash-low",
            "gemini-3.5-flash-high",
            "gemini-3.5-flash-medium",
            "gemini-3.5-flash-low",
            "gemini-3.1-pro-high",
            "gemini-3.1-pro-low",
            "claude-sonnet-4-6",
            "claude-opus-4-6-thinking",
            "gpt-oss-120b-medium",
        ]

    @hookimpl
    def llm_model_short_aliases(self) -> dict[str, str]:
        # Compact aliases for model picker labels and same-provider fan-out ids.
        return {
            "gemini-3.7-flash-high": "flash37h",
            "gemini-3.7-flash-medium": "flash37m",
            "gemini-3.7-flash-low": "flash37l",
            "gemini-3.6-flash-high": "flash36h",
            "gemini-3.6-flash-medium": "flash36m",
            "gemini-3.6-flash-low": "flash36l",
            "gemini-3.5-flash-high": "flash35h",
            "gemini-3.5-flash-medium": "flash35m",
            "gemini-3.5-flash-low": "flash35l",
            "gemini-3.1-pro-high": "pro31h",
            "gemini-3.1-pro-low": "pro31l",
            "claude-sonnet-4-6": "sonnet46",
            "claude-opus-4-6-thinking": "opus46t",
            "gpt-oss-120b-medium": "gptoss120m",
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
    def llm_auth_evidence(self) -> dict[str, list[str]]:
        # Antigravity's standard login uses an OS keyring, which doctor cannot
        # inspect offline without risking interactivity. Only env vars are
        # declared as deterministic evidence.
        return {
            "credential_paths": [],
            "api_key_env_vars": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        }

    @hookimpl
    def llm_install_metadata(self) -> dict[str, object]:
        return {
            "manager": "native",
            "scope": "user",
            "display_name": "Antigravity CLI",
            "vendor": "Antigravity",
            "docs_url": "https://antigravity.google/docs/cli-install",
            "self_update_argv": ["update"],
        }

    @hookimpl
    def llm_interactive_cli(self) -> dict[str, object]:
        return {
            "menu_key": "a",
            "bypass_args": ["--dangerously-skip-permissions"],
            "model_args": ["--model", "{model}"],
        }

    @hookimpl
    def llm_default_retry_config(self) -> ProviderRetryConfig:
        from .retry_config import (
            _RETRY_CONTINUATION_NUDGE,
            ProviderRetryConfig,
        )

        # Antigravity does not yet document a stable error contract, so these
        # patterns target the Google-stack transport/rate-limit/timeout failures
        # `agy` surfaces from the Gemini backend it routes to (gRPC status names
        # plus the CLI's own print timeout). They deliberately avoid the bare
        # HTTP "429"/"Too Many Requests" wording that the Codex provider already
        # owns, so the global error-based retry finder stays unambiguous. The
        # patterns are case-insensitive substrings; users can extend them via
        # ``llm_provider.retry.agy`` in sase.yml.
        return ProviderRetryConfig(
            max_retries=3,
            error_patterns=[
                "RESOURCE_EXHAUSTED",
                "UNAVAILABLE",
                "DEADLINE_EXCEEDED",
                "deadline exceeded",
                "rate limit",
                "print-timeout",
                "connection reset",
            ],
            wait_times=[60, 300, 1800],
            continuation_prompt=_RETRY_CONTINUATION_NUDGE,
            preserve_workspace=True,
        )

    @hookimpl
    def llm_default_usage_limit_config(self) -> ProviderUsageLimitConfig:
        from .usage_limit_config import ProviderUsageLimitConfig

        # Captured Antigravity quota failures use this prose and a reset hint
        # shaped like "Resets in 4h14m50s"; the parser consumes hours/minutes
        # and adds its grace buffer. Keep the transport-level Google API
        # patterns too, since Antigravity can surface backend errors directly.
        return ProviderUsageLimitConfig(
            patterns=[
                (
                    "individual quota reached. please upgrade your subscription "
                    "to increase your limits"
                ),
                "resource_exhausted",
                "quota exceeded",
                "insufficient_quota",
                "you exceeded your current quota",
            ],
        )

    def invocation_option_args(self, options: LLMInvocationOptions | None) -> list[str]:
        """Reject explicit effort; skip a config default (``agy`` has none).

        Antigravity exposes no reasoning-effort mechanism today, so the
        supported map is empty: an explicit ``%effort`` raises while a
        config-default effort is logged and skipped.
        """
        return effort_cli_args(
            options, provider_label="Antigravity (agy)", supported={}
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
        """Invoke the Antigravity CLI with the given prompt.

        Args:
            prompt: The preprocessed prompt to send.
            model_tier: Which model tier to resolve when no override is given.
            suppress_output: If True, suppress real-time output to console.
            model_override: If set, use this model name directly.
            options: Resolved per-invocation options. Antigravity supports no
                reasoning effort, so an explicit effort raises here before any
                subprocess launches; a config-default effort is skipped.

        Returns:
            An ``InvokeResult`` with the response text. ``usage`` is ``None``
            because ``agy`` exposes no stable token accounting in print mode.

        Raises:
            subprocess.CalledProcessError: If the ``agy`` process fails.
            FileNotFoundError: If the ``agy`` executable cannot be launched.
            LLMInvocationError: If an explicit reasoning effort is requested
                (Antigravity cannot honor any effort level).
        """
        agy_bin = _agy_bin()
        model = model_override if model_override else _TIER_TO_MODEL[model_tier]
        workspace_dir = _resolve_agy_workspace_dir()

        base_args = [
            agy_bin,
            "--print-timeout",
            _agy_print_timeout(),
            "--model",
            model,
            "--dangerously-skip-permissions",
            "--add-dir",
            workspace_dir,
        ]

        base_args.extend(self.invocation_option_args(options))

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
            provider_timer("Waiting for Antigravity") if not suppress_output else None
        )

        current_prompt = prompt
        accumulated_response = ""
        cycle = 0
        no_progress_continuations = 0
        max_no_progress_continuations = _agy_max_no_progress_continuations()

        while True:
            # The prompt is the value of `--print`, so it must stay adjacent to
            # the flag and be rebuilt each interrupt cycle.
            tool_call_snapshot = prepare_agy_tool_call_extraction(
                agy_bin,
                cwd=workspace_dir,
            )
            print_prompt = _wrap_agy_print_prompt(current_prompt)
            _validate_print_prompt_argv_transport(print_prompt)
            command_args = [*base_args, "--print", print_prompt]
            if timer_context:
                with timer_context:
                    content, stderr_content, return_code = self._run_subprocess(
                        command_args, suppress_output, cwd=workspace_dir
                    )
                    print()
            else:
                content, stderr_content, return_code = self._run_subprocess(
                    command_args, suppress_output, cwd=workspace_dir
                )

            if self._pending_interrupt_message is not None:
                user_msg = self._pending_interrupt_message
                self._pending_interrupt_message = None
                cycle += 1
                _log_interrupt(user_msg, cycle)
                accumulated_response = _join_response_parts(
                    accumulated_response,
                    content,
                )
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

            structural_progress = analyze_agy_turn_progress(tool_call_snapshot)
            append_agy_tool_call_events(tool_call_snapshot)
            is_no_progress, no_progress_reason = _classify_agy_no_progress(
                content,
                structural_progress,
            )
            if is_no_progress:
                no_progress_context = _join_response_parts(
                    accumulated_response,
                    content,
                )
                if no_progress_continuations >= max_no_progress_continuations:
                    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
                    artifact_hint = (
                        f" Artifacts: {artifacts_dir}." if artifacts_dir else ""
                    )
                    raise LLMInvocationError(
                        "Antigravity (`agy`) produced a no-progress print-mode "
                        "reply after "
                        f"{no_progress_continuations} continuation(s); refusing "
                        "to report it as success. Last reason: "
                        f"{no_progress_reason}. This usually means the model is "
                        "waiting on a background task that `agy --print` cannot "
                        f"resume.{artifact_hint}"
                    )
                no_progress_continuations += 1
                current_prompt = _build_no_progress_continuation_prompt(
                    prompt,
                    no_progress_context,
                )
                continue

            accumulated_response = _join_response_parts(accumulated_response, content)
            return InvokeResult(content=accumulated_response, usage=None)

    def _run_subprocess(
        self,
        args: list[str],
        suppress_output: bool,
        *,
        cwd: str,
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
                cwd=cwd,
            )
        except FileNotFoundError as exc:
            if not Path(cwd).is_dir():
                raise _agy_workspace_dir_not_found_error(cwd) from exc
            raise _agy_executable_not_found_error(args[0]) from exc

        start_interrupt_monitor(
            process,
            on_interrupt=lambda msg: setattr(self, "_pending_interrupt_message", msg),
        )

        return stream_process_output(
            process, suppress_output=suppress_output, clean_ansi=True
        )
