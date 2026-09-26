"""Meta Muse Code (`muse`) LLM provider implementation.

Muse is opt-in as a provider: it is selected by ``llm_provider.provider: muse``,
``%model:muse/<model>``, or ``SASE_MUSE_PATH``. It deliberately publishes no
``llm_autodetect_priority`` — ``muse`` is a generic executable name and SASE's
autodetect only checks PATH presence, so a same-named binary must never win
the default provider on its own. Model-alias routing is separate: the shipped
``@xsmall``/``@small``/``@medium`` pools list ``muse-spark-1.3-contributor``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from sase.core.paths import get_sase_managed_tmpdir
from sase.output import provider_timer

from ._effort_args import effort_cli_args
from ._hookspec import hookimpl
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
    from .usage.types import UsageProbeContext
    from .usage_limit_config import ProviderUsageLimitConfig

# (Model catalog, short aliases, advisories, and tier defaults live in the
# bundled ``models.yml`` manifest; see ``model_manifest.py``. Both tiers map
# to the full-price model on purpose — a tier mapping is SASE's own default
# choice of model, so it must never send a user's proprietary source into
# Meta's training corpus on the user's behalf.)

# Muse accepts every canonical level. Meta documents ``max`` reasoning for the
# standard Spark 1.3 model only; explicit requests for other model versions are
# left to the CLI to validate. Muse's own default is ``high``, so a run with no
# resolved effort shows blank in SASE while Muse actually used ``high``.
_EFFORT_CLI_ARGS: dict[str, list[str]] = {
    level: ["--reasoning-effort", level]
    for level in ("none", "minimal", "low", "medium", "high", "xhigh", "max")
}

_MUSE_PATH_ENV = "SASE_MUSE_PATH"
_MUSE_CLI_NAME = "muse"
_MUSE_SANDBOX_ENV = "SASE_MUSE_SANDBOX"

# Synchronous-execution ceiling for the legacy ``shell`` tool
# (``muse exec --enable-shell-tool``). Muse kills any command still running
# past this point and discards all of its output, so anything that can
# outlast it must go to a SASE monitor, chosen before the command starts.
_MUSE_SYNC_CEILING_SECONDS = 600
_MUSE_SYNC_CEILING_MINUTES = _MUSE_SYNC_CEILING_SECONDS // 60
# Wrap commands of uncertain length so a slow run still leaves evidence with
# a minute of headroom before the kill.
_MUSE_SYNC_COMMAND_TIMEOUT_SECONDS = _MUSE_SYNC_CEILING_SECONDS - 60
_MUSE_ENABLE_SHELL_TOOL_ARG = "--enable-shell-tool"

_MUSE_MAX_WAIT_CONTINUATIONS_ENV = "SASE_MUSE_MAX_WAIT_CONTINUATIONS"
_DEFAULT_MUSE_MAX_WAIT_CONTINUATIONS = 2
_MUSE_WAIT_CONTINUATION_NUDGE = (
    "Your previous reply ended the turn claiming to wait for a command, "
    "notification, or wake-up. This SASE session is single-turn: nothing "
    "will wake you, and nothing you started is still running. Finish now. "
    "Rerun anything unfinished in the foreground, or hand a genuinely long "
    "command to `/sase_monitor` with `--next`. Then submit your final "
    "declaration and give your final answer. If your work was already "
    "complete, restate your final answer without claiming to wait."
)


def _muse_max_wait_continuations() -> int:
    """Return the bounded stranded-wait continuation budget."""
    raw_value = os.environ.get(_MUSE_MAX_WAIT_CONTINUATIONS_ENV)
    if raw_value is None:
        return _DEFAULT_MUSE_MAX_WAIT_CONTINUATIONS
    try:
        return max(0, int(raw_value))
    except ValueError:
        return _DEFAULT_MUSE_MAX_WAIT_CONTINUATIONS


# The launcher otherwise checks for and swaps in a new binary hourly; a
# multi-hour agent run must not have its binary replaced mid-flight. Users
# update Muse through `sase agent-cli update muse` instead.
_MUSE_NO_AUTO_UPDATE_ENV = "MUSE_NO_AUTO_UPDATE"

_PROMPT_FILE_TMPDIR_PART = "muse-prompts"


def _resolve_muse_executable() -> str:
    """Return the Muse executable SASE should launch."""
    explicit_path = os.environ.get(_MUSE_PATH_ENV)
    if explicit_path:
        return explicit_path

    path_result = shutil.which(_MUSE_CLI_NAME)
    if path_result:
        return path_result

    return _MUSE_CLI_NAME


def _muse_executable_not_found_error(command: str) -> FileNotFoundError:
    """Build an actionable missing-Muse diagnostic."""
    return FileNotFoundError(
        "Unable to launch Muse Code executable "
        f"{command!r}. Set SASE_MUSE_PATH to the Muse binary, ensure 'muse' is "
        "discoverable on PATH, or run `sase agent-cli install muse`."
    )


def _muse_sandbox_enabled() -> bool:
    """Return whether the hardened ``SASE_MUSE_SANDBOX=on`` mode is requested."""
    return os.environ.get(_MUSE_SANDBOX_ENV, "").strip().lower() == "on"


def _safety_args() -> list[str]:
    """Return the safety flags for this run's sandbox mode.

    Muse's sandbox makes ``.git``, ``.muse``, and ``.agents`` read-only inside
    the workspace root, which breaks any in-run ``sase stitch create`` the agent
    performs through the ``sase_git_commit`` skill. The default therefore
    disables it, matching what SASE already does for Codex and OpenCode.
    ``SASE_MUSE_SANDBOX=on`` keeps the sandbox with networking enabled, which
    is genuinely useful for read-only research agents — at the documented cost
    of in-run commits failing.
    """
    if _muse_sandbox_enabled():
        return ["--sandbox-network", "enabled"]
    return ["--disable-sandbox"]


def _write_prompt_file(prompt: str) -> str:
    """Write *prompt* to a ``0o600`` file under SASE's managed temp root.

    ``muse exec`` reserves stdin for ``--api-key-stdin`` and SASE prompts
    routinely exceed comfortable argv limits, so ``--prompt-file`` is the only
    workable channel.
    """
    directory = get_sase_managed_tmpdir(_PROMPT_FILE_TMPDIR_PART)
    path = Path(directory) / f"prompt-{os.getpid()}-{uuid.uuid4().hex}.md"
    path.touch(mode=0o600)
    path.write_text(prompt, encoding="utf-8")
    return str(path)


def _muse_synchronous_shell_enabled() -> bool:
    """Return whether Muse runs commands in the legacy synchronous ``shell`` tool.

    Falls back to the registry default (on) when the flag cannot be resolved,
    so a broken flag snapshot fails closed toward no post-turn wake.
    """
    try:
        from sase.feature_flags import FeatureFlag, current_flags
        from sase.feature_flags.models import FeatureFlagError

        return current_flags().enabled(FeatureFlag.muse_synchronous_shell)
    except FeatureFlagError:
        return True


def _muse_single_turn_directive(*, synchronous: bool) -> str:
    """Return the mode-aware single-turn prompt prefix for Muse."""
    if synchronous:
        tool_sentence = (
            f"Your `shell` tool runs each command synchronously but kills any "
            f"command still running after {_MUSE_SYNC_CEILING_MINUTES} minutes "
            f"and discards all of its output, so blocking for up to about "
            f"{_MUSE_SYNC_COMMAND_TIMEOUT_SECONDS // 60} minutes is expected "
            f"and correct."
        )
    else:
        tool_sentence = "Your `bash` tool may move a long command to the background."
    if synchronous:
        inline_rule = "Run everything else inline."
    else:
        inline_rule = (
            "Run everything else inline, and read each backgrounded command's "
            "result before finishing."
        )
    if synchronous:
        wait_rule = "Never end your turn to wait."
    else:
        wait_rule = (
            "Never submit your final declaration or end your turn while a "
            "command you started is still running. SASE stops the Muse "
            "process about two minutes after your final declaration, killing "
            "anything still running."
        )
    return (
        "SASE single-turn instructions for Muse Code: this session is exactly "
        "one turn, and nothing can wake you after you end it. "
        f"{tool_sentence} Decide where a command runs before you start it: "
        "(1) Final verification: prefer prepared monitor completion "
        '(`/sase_final`, "Prepared Monitor Completion"). Run '
        "`sase final prepare` with your finished manifest (`bead_action: "
        "close` when the bead is done), then `sase monitor start -p verify -f "
        "<ref> -- <verification command>` (`just check` in SASE repos). "
        "Passing work lands with no further turn. (2) Commands that can take "
        f"longer than {_MUSE_SYNC_CEILING_MINUTES} minutes go to "
        "`/sase_monitor` with `--next` before you start them. Examples: full "
        "builds and installs, full test or visual suites, `just check-full`, "
        "CI, deploy, release, or rate-limit waits. The project's memory names "
        "its known-long commands. Combine dependent steps into one monitored "
        f"command. (3) {inline_rule} Wrap an unrecorded command of uncertain "
        f"length as `timeout {_MUSE_SYNC_COMMAND_TIMEOUT_SECONDS} <cmd> > "
        '<log> 2>&1; echo "exit=$?"; tail -n 80 <log>` so a slow run still '
        "leaves evidence. `sase tool run` output is retained; replay it with "
        "`sase tool show RUN -l`. Never background or detach a command (`&`, "
        "`nohup`, `setsid`). Never use cron, workflow, subagent, or snooze "
        "tools to wait. Never cancel or rerun an in-flight command to move it "
        f"to a monitor. {wait_rule}"
    )


def _wrap_muse_prompt(prompt: str, *, synchronous: bool) -> str:
    """Prefix *prompt* with the mode-aware single-turn directive.

    Muse has no append-system-prompt flag, so the directive travels as a
    prompt prefix the way ``agy.py`` wraps its print-mode prompt.
    """
    directive = _muse_single_turn_directive(synchronous=synchronous)
    return f"{directive}\n\n--- User Prompt ---\n{prompt}"


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


class MuseProvider(LLMProvider):
    """LLM provider that invokes Meta's Muse Code CLI."""

    _pending_interrupt_message: str | None = None

    def resolve_model_name(self, model_tier: ModelTier = "large") -> str:
        """Return the Muse model name for the given tier."""
        return provider_tier_model("muse", model_tier)

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
        return _MUSE_CLI_NAME

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
            "env": {_MUSE_NO_AUTO_UPDATE_ENV: "1"},
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
            context, executable=context.executable or _resolve_muse_executable()
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

    def invocation_option_args(self, options: LLMInvocationOptions | None) -> list[str]:
        """Translate a resolved reasoning effort into ``--reasoning-effort`` args."""
        return effort_cli_args(
            options, provider_label="Muse Code", supported=_EFFORT_CLI_ARGS
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
        synchronous_shell = _muse_synchronous_shell_enabled()
        prompt = _wrap_muse_prompt(prompt, synchronous=synchronous_shell)

        if model_tier == "large":
            extra_args_env = os.environ.get(
                "SASE_LLM_LARGE_ARGS", os.environ.get("SASE_MUSE_LARGE_ARGS")
            )
        else:
            extra_args_env = os.environ.get(
                "SASE_LLM_SMALL_ARGS", os.environ.get("SASE_MUSE_SMALL_ARGS")
            )

        base_args = [
            _resolve_muse_executable(),
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
                *_safety_args(),
                # Offer request_user_input but auto-cancel its prompts.
                "--user-input-auto-resolve",
                "--no-foreign-personal-context",
            ]
        )

        if synchronous_shell:
            # A duplicate boolean flag is a `muse exec` usage error (exit 2).
            extra_tokens = extra_args_env.split() if extra_args_env else []
            if _MUSE_ENABLE_SHELL_TOOL_ARG not in extra_tokens:
                base_args.append(_MUSE_ENABLE_SHELL_TOOL_ARG)

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
        max_wait_continuations = _muse_max_wait_continuations()

        while True:
            # The prompt goes through a 0o600 managed temp file rather than
            # argv or stdin, and is removed as soon as the cycle ends.
            prompt_file = _write_prompt_file(current_prompt)
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
                _log_interrupt(user_msg, cycle)
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
                    f"--- Required Continuation ---\n"
                    f"{_MUSE_WAIT_CONTINUATION_NUDGE}"
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
        env[_MUSE_NO_AUTO_UPDATE_ENV] = "1"

        try:
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )
        except FileNotFoundError as exc:
            raise _muse_executable_not_found_error(args[0]) from exc

        start_interrupt_monitor(
            process,
            on_interrupt=lambda msg: setattr(self, "_pending_interrupt_message", msg),
        )
        start_completion_watchdog(process, runtime="muse")

        return stream_and_parse_muse_json_output(
            process, suppress_output=suppress_output, session_id=session_id
        )
