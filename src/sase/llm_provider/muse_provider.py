"""Meta Muse Code (`muse`) LLM provider class.

Muse is opt-in as a provider: it is selected by ``llm_provider.provider: muse``,
``%model:muse/<model>``, or ``SASE_MUSE_PATH``. It deliberately publishes no
``llm_autodetect_priority`` — ``muse`` is a generic executable name and SASE's
autodetect only checks PATH presence, so a same-named binary must never win
the default provider on its own. Model-alias routing is separate: the shipped
``@xsmall``/``@small``/``@medium`` pools list ``muse-spark-1.3-contributor``.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from sase.output import provider_timer

from ._effort_args import effort_cli_args
from ._hookspec import hookimpl
from ._muse_directive import (
    MUSE_ENABLE_SHELL_TOOL_ARG,
    MUSE_SYNC_CEILING_SECONDS,
    MUSE_WAIT_CONTINUATION_NUDGE,
    muse_max_wait_continuations,
    muse_synchronous_shell_enabled,
    wrap_muse_prompt,
)
from ._muse_launch import (
    MUSE_CLI_NAME,
    MUSE_EFFORT_CLI_ARGS,
    MUSE_NO_AUTO_UPDATE_ENV,
    log_muse_interrupt,
    muse_executable_not_found_error,
    muse_safety_args,
    resolve_muse_executable,
    write_muse_prompt_file,
)
from ._subprocess import (
    start_completion_watchdog,
    start_interrupt_monitor,
    stream_and_parse_muse_json_output,
)
from ._wait_guard import log_wait_guard as _log_wait_guard
from ._wait_signals import ends_with_wait_claim
from .base import LLMProvider
from .model_manifest import (
    provider_model_advisories,
    provider_model_names,
    provider_short_aliases,
    provider_tier_model,
)
from .types import InvokeResult, LLMInvocationError, LLMInvocationOptions, ModelTier

if TYPE_CHECKING:
    from .retry_config import ProviderRetryConfig
    from .usage.types import UsageProbeContext
    from .usage_limit_config import ProviderUsageLimitConfig


class MuseProvider(LLMProvider):
    """LLM provider that invokes Meta's Muse Code CLI."""

    _pending_interrupt_message: str | None = None

    def resolve_model_name(self, model_tier: ModelTier = "large") -> str:
        """Return the Muse model name for the given tier."""
        return provider_tier_model("muse", model_tier)

    def sync_ceiling_seconds(self) -> int | None:
        """Return the legacy ``shell`` tool's hard kill ceiling, when active."""
        if muse_synchronous_shell_enabled():
            return MUSE_SYNC_CEILING_SECONDS
        return None

    @hookimpl
    def llm_sync_ceiling_seconds(self) -> int | None:
        return self.sync_ceiling_seconds()

    @hookimpl
    def llm_provider_name(self) -> str:
        return "muse"

    @hookimpl
    def llm_provider_short_name(self) -> str:
        return "mus"

    @hookimpl
    def llm_resolve_model_name(self, model_tier: ModelTier) -> str:
        return self.resolve_model_name(model_tier)

    @hookimpl
    def llm_known_model_names(self) -> list[str]:
        return list(provider_model_names("muse"))

    @hookimpl
    def llm_model_short_aliases(self) -> dict[str, str]:
        return provider_short_aliases("muse")

    @hookimpl
    def llm_model_advisories(self) -> dict[str, dict[str, str]]:
        # The Contributor model is a real feature and a real hazard. It stays
        # fully reachable by name; this makes the trade visible everywhere the
        # model is, so nobody agrees to it without seeing it.
        return provider_model_advisories("muse")

    @hookimpl
    def llm_skill_template_context(self) -> dict[str, str]:
        return {
            "provider_name": "Muse Code",
            "provider_tool_name": "Muse Code",
            "provider_native_ask_tool": "request_user_input",
        }

    @hookimpl
    def llm_skill_deploy_subpath(self) -> str:
        # Muse loads skills from ``~/.config/muse/skills/<name>/SKILL.md``.
        # Without this, Muse picks up SASE's Claude-rendered copies from
        # ``~/.claude/skills`` and reads them as if it were Claude Code.
        return ".config/muse"

    @hookimpl
    def llm_cli_status_color(self) -> str:
        return "#3D9BFF"

    @hookimpl
    def llm_autodetect_cli_name(self) -> str:
        return MUSE_CLI_NAME

    @hookimpl
    def llm_auth_evidence(self) -> dict[str, list[str]]:
        return {
            "credential_paths": ["$MUSE_AUTH_PATH", "~/.config/muse/auth.json"],
            "api_key_env_vars": ["META_API_KEY"],
        }

    @hookimpl
    def llm_install_metadata(self) -> dict[str, object]:
        return {
            "manager": "script",
            "display_name": "Muse Code",
            "vendor": "Meta",
            "docs_url": (
                "https://developer.meta.com/ai/resources/blog/build-with-muse-code/"
            ),
            "version_argv": ["--version"],
            # ``muse --version`` prints ``Muse Code 0.1.0 (0.1.0-R708.1)``; the
            # default semver regex would keep only ``0.1.0`` and discard the
            # release id the channel actually serves.
            "version_regex": r"\((?P<version>[^)]+)\)",
            "latest_version_url": "https://api.meta.ai/muse-code/channels/muse-stable",
            "latest_version_json_field": "version",
            # ``0.1.0-R708.1`` is not a valid PEP 440 version, so the default
            # comparator silently reports "no known updates" forever.
            "version_compare": "exact",
            # With MUSE_SYNC_UPDATE=1 the launcher updates itself and the
            # binary and then execs the binary, so the update command and the
            # version probe are literally the same command.
            "self_update_argv": ["--version"],
            "self_update_env": {"MUSE_SYNC_UPDATE": "1"},
            "install_script_url": "https://dev.meta.ai/install.sh",
            # The installer writes the launcher to
            # ``${MUSE_INSTALL_DIR:-~/.local/bin}/muse``; declaring both lets
            # `sase agent-cli install` name the target directory up front and
            # find the binary afterwards when it is not yet on PATH.
            "install_dir": "~/.local/bin",
            "install_dir_env": "MUSE_INSTALL_DIR",
            # Without MUSE_UPGRADE_MODE=1 the installer appends `export PATH=`
            # lines to the user's shell rc files.
            "install_env": {"MUSE_UPGRADE_MODE": "1"},
        }

    @hookimpl
    def llm_interactive_cli(self) -> dict[str, object]:
        # Mirror the headless invoke env: a multi-hour session must not have
        # its binary swapped mid-flight by the Muse launcher's auto-update.
        return {
            "menu_key": "m",
            "bypass_args": ["--yolo"],
            "model_args": ["--model", "{model}"],
            "env": {MUSE_NO_AUTO_UPDATE_ENV: "1"},
        }

    @hookimpl
    def llm_usage_capabilities(self) -> dict[str, object]:
        return {
            "probe": True,
            "passive_events": False,
            "min_probe_interval_seconds": 180,
        }

    @hookimpl
    def llm_usage_probe(self, context: UsageProbeContext) -> dict[str, object] | None:
        from .usage.muse import collect_muse_usage

        return collect_muse_usage(
            context, executable=context.executable or resolve_muse_executable()
        )

    @hookimpl
    def llm_default_usage_limit_config(self) -> ProviderUsageLimitConfig:
        from .usage_limit_config import ProviderUsageLimitConfig

        # No usage-limit wording has been confirmed from this provider's
        # shipped artifacts (epic sase-n4 research). This conservative
        # baseline is unverified; tighten it once a real captured message is
        # available.
        return ProviderUsageLimitConfig(
            patterns=[
                "usage limit reached",
                "quota exceeded",
                "insufficient_quota",
            ],
        )

    @hookimpl
    def llm_default_retry_config(self) -> ProviderRetryConfig:
        from .retry_config import (
            _RETRY_CONTINUATION_NUDGE,
            ProviderRetryConfig,
        )

        # Muse has no headless resume, so a SASE retry starts a fresh
        # `muse exec` session (new `--session-id`) with the nudge prepended.
        # On-disk edits survive because `preserve_workspace=True`. A fresh
        # session is also what escapes the session-scoped 504s seen here.
        return ProviderRetryConfig(
            max_retries=3,
            error_patterns=[
                # Captured live from the 2026-10-01 `bob-cli-31.4` failure
                # (Muse 1.4.2-R4684.1). It is Muse's zero-byte chain terminal,
                # printed after its own turn retry budget is exhausted.
                "no data is reaching this machine from the model service",
                # The machine error kinds Muse lists in that give-up summary's
                # `all [...]` suffix. They are a second anchor in case a later
                # build rewords the prose, the same dual-anchor rationale as
                # Grok's `max_tokens_truncation`.
                "model_stream_first_event_timeout",
                "model_stream_idle_timeout",
                # The sibling give-up prose for the transport, service,
                # router, and stream-ended failure classes. It comes from
                # scanning the shipped binary and has not been observed live.
                "kept failing until the whole turn retry budget was exhausted",
            ],
            wait_times=[60, 300, 1800],
            continuation_prompt=_RETRY_CONTINUATION_NUDGE,
            preserve_workspace=True,
        )

    def invocation_option_args(self, options: LLMInvocationOptions | None) -> list[str]:
        """Translate a resolved reasoning effort into ``--reasoning-effort`` args."""
        return effort_cli_args(
            options, provider_label="Muse Code", supported=MUSE_EFFORT_CLI_ARGS
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
        """Invoke Muse Code with the given prompt.

        Args:
            prompt: The preprocessed prompt to send.
            model_tier: Which model tier to use ("large" or "small").
            suppress_output: If True, suppress real-time output to console.
            model_override: If set, use this model name directly instead of
                mapping from ``model_tier``.
            options: Resolved per-invocation options; the reasoning effort is
                translated into ``--reasoning-effort`` args.

        Returns:
            An ``InvokeResult`` with the response text and token usage. Muse's
            stdout stream carries no token counts, so usage is recovered from
            the session log SASE names through ``--session-id``.

        Raises:
            subprocess.CalledProcessError: If the Muse CLI process fails. Exit
                code 2 is a CLI usage error rather than a model failure and is
                labeled as such in the raised diagnostics.
        """
        model = (
            model_override if model_override else self.resolve_model_name(model_tier)
        )
        # Wrap once, at the top, so the interrupt path's reconstructed context
        # and the next phase's guard also carry the directive.
        synchronous_shell = muse_synchronous_shell_enabled()
        prompt = wrap_muse_prompt(prompt, synchronous=synchronous_shell)

        if model_tier == "large":
            extra_args_env = os.environ.get(
                "SASE_LLM_LARGE_ARGS", os.environ.get("SASE_MUSE_LARGE_ARGS")
            )
        else:
            extra_args_env = os.environ.get(
                "SASE_LLM_SMALL_ARGS", os.environ.get("SASE_MUSE_SMALL_ARGS")
            )

        base_args = [
            resolve_muse_executable(),
            "exec",
            "--json",
            "--workspace",
            os.getcwd(),
            "--model",
            model,
        ]

        base_args.extend(self.invocation_option_args(options))

        base_args.extend(
            [
                "--trust-workspace",
                # Approvals must go: a headless run cannot answer them.
                "--disable-approval",
                *muse_safety_args(),
                # Offer request_user_input but auto-cancel its prompts.
                "--user-input-auto-resolve",
                "--no-foreign-personal-context",
            ]
        )

        if synchronous_shell:
            # A duplicate boolean flag is a `muse exec` usage error (exit 2).
            extra_tokens = extra_args_env.split() if extra_args_env else []
            if MUSE_ENABLE_SHELL_TOOL_ARG not in extra_tokens:
                base_args.append(MUSE_ENABLE_SHELL_TOOL_ARG)

        if extra_args_env:
            for arg in extra_args_env.split():
                base_args.append(arg)

        timer_context = (
            provider_timer("Waiting for Muse Code") if not suppress_output else None
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
        wait_continuations = 0
        max_wait_continuations = muse_max_wait_continuations()

        while True:
            # The prompt goes through a 0o600 managed temp file rather than
            # argv or stdin, and is removed as soon as the cycle ends.
            prompt_file = write_muse_prompt_file(current_prompt)
            # SASE generates the session id rather than letting Muse pick one:
            # it is the handle that locates the session log, which is where
            # Muse's token usage actually lives.
            session_id = str(uuid.uuid4())
            try:
                command_args = [
                    *base_args,
                    "--session-id",
                    session_id,
                    "--prompt-file",
                    prompt_file,
                ]

                if timer_context:
                    with timer_context:
                        content, stderr_content, return_code, usage = (
                            self._run_subprocess(
                                command_args, suppress_output, session_id
                            )
                        )
                        print()
                else:
                    content, stderr_content, return_code, usage = self._run_subprocess(
                        command_args, suppress_output, session_id
                    )
            finally:
                Path(prompt_file).unlink(missing_ok=True)

            for key in total_usage:
                total_usage[key] += usage.get(key, 0)

            if self._pending_interrupt_message is not None:
                user_msg = self._pending_interrupt_message
                self._pending_interrupt_message = None
                cycle += 1
                log_muse_interrupt(user_msg, cycle)
                accumulated_response = (
                    accumulated_response + "\n\n" + content.strip()
                ).strip()
                # Muse has no headless resume (`muse resume` is interactive
                # only), so reconstruct the context the way Codex/OpenCode do.
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
            # A clean exit whose reply still ends by claiming to wait is
            # stranded: with the synchronous shell nothing can be pending, and
            # with managed `bash` a watchdog teardown reports the same way.
            # Either way nothing will wake the model, so continue with a nudge
            # or fail loudly rather than recording the wait as success.
            if ends_with_wait_claim(content):
                cycle += 1
                _log_wait_guard("stranded_wait_claim", cycle)
                if wait_continuations >= max_wait_continuations:
                    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
                    artifact_hint = (
                        f" Artifacts: {artifacts_dir}." if artifacts_dir else ""
                    )
                    raise LLMInvocationError(
                        "Muse produced a wait-claim reply after "
                        f"{wait_continuations} continuation(s); refusing to "
                        "report it as success. Reason: "
                        "stranded_wait_claim. Nothing will wake the model, and "
                        f"nothing it started is still running.{artifact_hint}"
                    )
                wait_continuations += 1
                # Muse has no headless resume, so reconstruct the context the
                # way the interrupt path does.
                current_prompt = (
                    f"{prompt}\n\n"
                    f"--- Work So Far ---\n{accumulated_response}\n\n"
                    "--- Required Continuation ---\n"
                    f"{MUSE_WAIT_CONTINUATION_NUDGE}"
                )
                continue
            return InvokeResult(content=accumulated_response, usage=total_usage)

    def _run_subprocess(
        self,
        args: list[str],
        suppress_output: bool,
        session_id: str | None = None,
    ) -> tuple[str, str, int, dict[str, int]]:
        """Run the Muse Code subprocess and parse its JSONL event stream."""
        env = os.environ.copy()
        env[MUSE_NO_AUTO_UPDATE_ENV] = "1"

        try:
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
        except FileNotFoundError as exc:
            raise muse_executable_not_found_error(args[0]) from exc

        start_interrupt_monitor(
            process,
            on_interrupt=lambda msg: setattr(self, "_pending_interrupt_message", msg),
        )
        start_completion_watchdog(process, runtime="muse")

        return stream_and_parse_muse_json_output(
            process, suppress_output=suppress_output, session_id=session_id
        )


__all__ = ["MuseProvider"]
