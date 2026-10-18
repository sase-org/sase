"""Codex (OpenAI CLI agent) LLM provider implementation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from sase.feature_flags.managed import project_is_sase_managed
from sase.output import provider_timer

from ._codex_home import (
    active_explicit_codex_delivery,
    codex_subprocess_env,
    is_sase_managed_codex_home,
    real_codex_home,
    resolve_codex_project_dir,
)
from ._codex_instructions import (
    CODEX_PATH_ENV,
    CODEX_TURN_INTEGRITY_ERROR_PREFIX,
    EFFORT_CLI_ARGS,
    coerce_stream_result,
    codex_executable_not_found_error,
    explicit_instructions_enabled,
    log_interrupt,
    max_wait_continuations,
    resolve_codex_executable,
    single_turn_directive,
    stranded_handoff_continuation_nudge,
)
from ._effort_args import effort_cli_args
from ._hookspec import hookimpl
from .instruction_delivery import (
    CHANNEL_CODEX_ROOT,
    current_instruction_delivery,
    legacy_instruction_delivery,
)
from ._subprocess import (
    start_completion_watchdog,
    start_interrupt_monitor,
    stream_and_parse_codex_json_output,
)
from ._subprocess_codex import CodexStreamResult
from ._wait_guard import log_wait_guard
from .base import LLMProvider
from .model_manifest import (
    provider_model_names,
    provider_short_aliases,
    provider_tier_model,
)
from .types import InvokeResult, LLMInvocationError, LLMInvocationOptions, ModelTier

if TYPE_CHECKING:
    from .retry_config import ProviderRetryConfig
    from .usage.types import UsageProbeContext
    from .usage_limit_config import ProviderUsageLimitConfig

_CODEX_NEWER_VERSION_MARKER = "requires a newer version of Codex"


class CodexProvider(LLMProvider):
    """LLM provider that invokes the Codex CLI tool."""

    _pending_interrupt_message: str | None = None

    def resolve_model_name(self, model_tier: ModelTier = "large") -> str:
        """Return the Codex model name for the given tier."""
        return provider_tier_model("codex", model_tier)

    @hookimpl
    def llm_provider_name(self) -> str:
        return "codex"

    @hookimpl
    def llm_provider_short_name(self) -> str:
        return "cdx"

    @hookimpl
    def llm_resolve_model_name(self, model_tier: ModelTier) -> str:
        return self.resolve_model_name(model_tier)

    @hookimpl
    def llm_known_model_names(self) -> list[str]:
        return list(provider_model_names("codex"))

    @hookimpl
    def llm_model_short_aliases(self) -> dict[str, str]:
        return provider_short_aliases("codex")

    @hookimpl
    def llm_skill_template_context(self) -> dict[str, str]:
        return {
            "provider_name": "Codex",
            "provider_tool_name": "Codex",
            "provider_native_ask_tool": "ask_user",
        }

    @hookimpl
    def llm_autodetect_priority(self) -> int:
        return 10

    @hookimpl
    def llm_autodetect_cli_name(self) -> str:
        return "codex"

    @hookimpl
    def llm_auth_evidence(self) -> dict[str, list[str]]:
        return {
            "credential_paths": ["$CODEX_HOME/auth.json", "~/.codex/auth.json"],
            "api_key_env_vars": ["OPENAI_API_KEY"],
        }

    @hookimpl
    def llm_install_metadata(self) -> dict[str, object]:
        return {
            "manager": "npm",
            "package": "@openai/codex",
            "scope": "global",
            "display_name": "Codex CLI",
            "vendor": "OpenAI",
            "docs_url": "https://developers.openai.com/codex/cli/",
            "self_update_argv": ["update"],
            "latest_version_package": "@openai/codex",
            "brew_package": "codex",
        }

    @hookimpl
    def llm_interactive_cli(self) -> dict[str, object]:
        return {
            "menu_key": "x",
            "bypass_args": ["--dangerously-bypass-approvals-and-sandbox"],
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
                "exceeded retry limit",
                "429 Too Many Requests",
                "Too Many Requests",
                "rate limit",
                "failed to connect to websocket",
                "Selected model is at capacity",
                CODEX_TURN_INTEGRITY_ERROR_PREFIX,
            ],
            wait_times=[60, 300, 1800],
            continuation_prompt=_RETRY_CONTINUATION_NUDGE,
            preserve_workspace=True,
        )

    @hookimpl
    def llm_default_usage_limit_config(self) -> ProviderUsageLimitConfig:
        from .usage_limit_config import ProviderUsageLimitConfig

        # The literal message family shipped in the @openai/codex native
        # binary (epic sase-n4 research). The same binary also emits a reset
        # instant with the carrier sentence, in local time with no zone
        # marker: "Try again at %b %-d<ord>, %Y %-I:%M %p." (ordinal day,
        # year always present, e.g. "Try again at Aug 20th, 2026 6:38 AM.")
        # or a bare "%-I:%M %p." once the date rolls over to today. No
        # pattern change is needed here since "you've hit your usage limit"
        # already matches the carrier sentence; usage_limit_config.py parses
        # the reset instant out of it.
        return ProviderUsageLimitConfig(
            patterns=[
                "you've hit your usage limit",
                "usage limit reached",
                "to get more access now, send a request to your admin",
            ],
            exclude_patterns=["usage limit approaching"],
        )

    @hookimpl
    def llm_usage_capabilities(self) -> dict[str, object]:
        # Normal `codex exec --json` token events are not subscription
        # capacity (epic sase-y5 plan); collection is probe-only.
        return {
            "probe": True,
            "passive_events": False,
            "min_probe_interval_seconds": 120,
        }

    @hookimpl
    def llm_usage_probe(self, context: UsageProbeContext) -> dict[str, object] | None:
        from .usage.codex_collector import collect_codex_usage

        return collect_codex_usage(context)

    def invocation_option_args(self, options: LLMInvocationOptions | None) -> list[str]:
        """Translate a resolved reasoning effort into ``-c`` config args."""
        return effort_cli_args(
            options, provider_label="Codex", supported=EFFORT_CLI_ARGS
        )

    def instruction_delivery(self) -> dict[str, object]:
        if not explicit_instructions_enabled():
            return legacy_instruction_delivery(reason="flag_disabled")
        return {
            "root": {
                "status": "explicit",
                "channel": CHANNEL_CODEX_ROOT,
                "max_bytes": 32 * 1024,
            },
            "subagent": {"status": "inherits_root"},
        }

    @hookimpl
    def llm_instruction_delivery(self) -> dict[str, object]:
        return self.instruction_delivery()

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
        """Invoke Codex CLI with the given prompt.

        Args:
            prompt: The preprocessed prompt to send.
            model_tier: Which model tier to use ("large" or "small").
            suppress_output: If True, suppress real-time output to console.
            model_override: If set, use this model name directly instead of
                mapping from ``model_tier``.
            options: Resolved per-invocation options; the reasoning effort is
                translated into ``-c model_reasoning_effort=...`` args.

        Returns:
            An ``InvokeResult`` with the response text (usage is ``None``).

        Raises:
            subprocess.CalledProcessError: If the Codex CLI process fails.
                Transient transport/rate-limit failures (e.g. ``429 Too Many
                Requests`` or websocket connection errors) are matched by the
                built-in ``llm_default_retry_config`` so the workflow retry
                subsystem can recover instead of terminating.
        """
        model = (
            model_override if model_override else self.resolve_model_name(model_tier)
        )

        delivery = current_instruction_delivery()
        active_root = (
            delivery.root
            if delivery is not None and delivery.provider == "codex"
            else None
        )
        explicit_text = (
            delivery.root.text
            if delivery is not None and active_explicit_codex_delivery()
            else None
        )
        developer_instructions = explicit_text or single_turn_directive()

        base_args = [
            resolve_codex_executable(),
            "exec",
            "--model",
            model,
            "--dangerously-bypass-approvals-and-sandbox",
            "--json",
            "--color",
            "never",
            "--skip-git-repo-check",
            "-c",
            f"developer_instructions={json.dumps(developer_instructions)}",
            "-",
        ]

        if explicit_text and project_is_sase_managed(Path(resolve_codex_project_dir())):
            base_args.extend(["-c", "project_doc_max_bytes=0"])

        base_args.extend(self.invocation_option_args(options))

        # Parse additional args from environment variable based on tier
        if model_tier == "large":
            extra_args_env = os.environ.get(
                "SASE_LLM_LARGE_ARGS", os.environ.get("SASE_CODEX_LARGE_ARGS")
            )
        else:
            extra_args_env = os.environ.get(
                "SASE_LLM_SMALL_ARGS", os.environ.get("SASE_CODEX_SMALL_ARGS")
            )

        if extra_args_env:
            for arg in extra_args_env.split():
                base_args.append(arg)

        timer_context = (
            provider_timer("Waiting for Codex") if not suppress_output else None
        )

        current_prompt = prompt
        accumulated_response = ""
        cycle = 0
        wait_continuations = 0
        max_continuations = max_wait_continuations()
        while True:
            if timer_context:
                with timer_context:
                    stream_result = coerce_stream_result(
                        self._run_subprocess(base_args, current_prompt, suppress_output)
                    )
                    print()
            else:
                stream_result = coerce_stream_result(
                    self._run_subprocess(base_args, current_prompt, suppress_output)
                )
            response_content = stream_result.content
            stderr_content = stream_result.stderr_content
            return_code = stream_result.return_code

            if (
                stream_result.thread_id
                and delivery is not None
                and delivery.provider == "codex"
                and active_root is not None
                and active_root.plan.status == "explicit"
            ):
                delivery.record_session(stream_result.thread_id)

            # Check for user interrupt before error handling
            if self._pending_interrupt_message is not None:
                user_msg = self._pending_interrupt_message
                self._pending_interrupt_message = None
                cycle += 1
                log_interrupt(user_msg, cycle)
                accumulated_response = (
                    accumulated_response + "\n\n" + response_content.strip()
                ).strip()
                # Codex has no session persistence — reconstruct context
                current_prompt = (
                    f"{prompt}\n\n"
                    f"--- Work So Far ---\n{accumulated_response}\n\n"
                    f"--- User Message ---\n{user_msg}\n\n"
                    "Continue working, incorporating the user's message above."
                )
                continue

            if return_code != 0:
                stderr_content, response_content = _annotate_stale_codex_cli(
                    stderr_content, response_content, base_args[0]
                )
                raise subprocess.CalledProcessError(
                    return_code,
                    base_args,
                    output=response_content,
                    stderr=stderr_content,
                )

            accumulated_response = (
                accumulated_response + "\n\n" + response_content.strip()
            ).strip()
            stranded_handoff_commands = tuple(
                command
                for command in stream_result.stranded_commands
                if command.is_handoff
            )
            if stranded_handoff_commands:
                guard_cycle = wait_continuations + 1
                log_wait_guard("stranded_handoff_command", guard_cycle)
                command_label = (
                    next(
                        (
                            command.command
                            for command in stranded_handoff_commands
                            if command.command
                        ),
                        None,
                    )
                    or stranded_handoff_commands[0].command_id
                )
                if wait_continuations >= max_continuations:
                    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
                    artifact_hint = (
                        f" Artifacts: {artifacts_dir}." if artifacts_dir else ""
                    )
                    raise LLMInvocationError(
                        "Codex stranded a SASE handoff command after "
                        f"{wait_continuations} continuation(s); refusing to report "
                        "it as success. Reason: stranded_handoff_command. "
                        f"Command: {command_label}.{artifact_hint}"
                    )
                wait_continuations += 1
                current_prompt = (
                    f"{prompt}\n\n"
                    f"--- Work So Far ---\n{accumulated_response}\n\n"
                    "--- Required Continuation ---\n"
                    f"{stranded_handoff_continuation_nudge(stranded_handoff_commands)}"
                )
                continue
            if stream_result.integrity_error:
                raise LLMInvocationError(stream_result.integrity_error)
            return InvokeResult(content=accumulated_response)

    # ------------------------------------------------------------------
    # Subprocess runner
    # ------------------------------------------------------------------

    def _run_subprocess(
        self,
        args: list[str],
        prompt: str,
        suppress_output: bool,
    ) -> CodexStreamResult:
        """Run the Codex CLI subprocess.

        Args:
            args: Command-line arguments.
            prompt: Prompt to write to stdin.
            suppress_output: If True, suppress output.

        Returns:
            Parsed output and any stranded-command facts.
        """
        with codex_subprocess_env() as env:
            try:
                process = subprocess.Popen(
                    args,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=env,
                )
            except FileNotFoundError as exc:
                raise codex_executable_not_found_error(args[0]) from exc

            # Write prompt to stdin
            if process.stdin:
                process.stdin.write(prompt)
                process.stdin.close()

            start_interrupt_monitor(
                process,
                on_interrupt=lambda msg: setattr(
                    self, "_pending_interrupt_message", msg
                ),
            )
            start_completion_watchdog(process, runtime="codex")

            return stream_and_parse_codex_json_output(
                process, suppress_output=suppress_output
            )


def _annotate_stale_codex_cli(
    stderr: str, output: str, executable: str
) -> tuple[str, str]:
    """Name the launched binary when Codex rejects its own version."""
    if (
        _CODEX_NEWER_VERSION_MARKER not in stderr
        and _CODEX_NEWER_VERSION_MARKER not in output
    ):
        return stderr, output
    hint = (
        f"SASE launched {executable}. Run `sase agent-cli list` to inspect "
        f"shadowed installs, or pin {CODEX_PATH_ENV}."
    )
    if hint in stderr or hint in output:
        return stderr, output
    if _CODEX_NEWER_VERSION_MARKER in stderr:
        return _append_hint(stderr, hint), output
    return stderr, _append_hint(output, hint)


def _append_hint(text: str, hint: str) -> str:
    stripped = text.rstrip()
    return f"{stripped}\n{hint}" if stripped else hint


__all__ = [
    "CodexProvider",
    "is_sase_managed_codex_home",
    "real_codex_home",
    "resolve_codex_executable",
    "single_turn_directive",
]
