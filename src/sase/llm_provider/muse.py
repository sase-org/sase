"""Meta Muse Code (`muse`) LLM provider implementation.

Muse is opt-in: it is selected by ``llm_provider.provider: muse``,
``%model:muse/<model>``, or ``SASE_MUSE_PATH``. It deliberately publishes no
``llm_autodetect_priority`` — ``muse`` is a generic executable name and SASE's
autodetect only checks PATH presence, so a same-named binary must never win
the default provider on its own.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from sase.core.paths import get_sase_managed_tmpdir
from sase.output import provider_timer

from ._effort_args import effort_cli_args
from ._hookspec import hookimpl
from ._subprocess import start_interrupt_monitor, stream_and_parse_muse_json_output
from .base import LLMProvider
from .types import InvokeResult, LLMInvocationOptions, ModelTier

# Both tiers map to the full-price model on purpose. ``small`` is what
# ``@cheap``/``@cheaper`` reach for automatically, and
# ``muse-spark-1.2-contributor`` is trained on its inputs and outputs — SASE
# must never route a user's proprietary source into Meta's training corpus
# without being told to. The Contributor model stays fully reachable by name.
_TIER_TO_MODEL: dict[ModelTier, str] = {
    "large": "muse-spark-1.2",
    "small": "muse-spark-1.2",
}

_CONTRIBUTOR_MODEL = "muse-spark-1.2-contributor"

# Muse accepts ``none|minimal|low|medium|high|xhigh|ultra`` and rejects ``max``
# by name, so SASE's canonical ``max`` maps onto Muse's ``ultra``. Muse is the
# first provider to cover all seven canonical levels. Muse's own default is
# ``high``, so a run with no resolved effort shows blank in SASE while Muse
# actually used ``high``.
_EFFORT_CLI_ARGS: dict[str, list[str]] = {
    level: ["--reasoning-effort", level]
    for level in ("none", "minimal", "low", "medium", "high", "xhigh")
} | {"max": ["--reasoning-effort", "ultra"]}

_MUSE_PATH_ENV = "SASE_MUSE_PATH"
_MUSE_CLI_NAME = "muse"
_MUSE_SANDBOX_ENV = "SASE_MUSE_SANDBOX"

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
    the workspace root, which breaks any in-run ``sase commit`` the agent
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
        return _TIER_TO_MODEL[model_tier]

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
        return [
            "muse-spark-1.2",
            _CONTRIBUTOR_MODEL,
            "muse-spark-1.1",
        ]

    @hookimpl
    def llm_model_short_aliases(self) -> dict[str, str]:
        return {
            "muse-spark-1.2": "spark12",
            _CONTRIBUTOR_MODEL: "spark12c",
            "muse-spark-1.1": "spark11",
        }

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
        return "#0064E0"

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
            # Without MUSE_UPGRADE_MODE=1 the installer appends `export PATH=`
            # lines to the user's shell rc files.
            "install_env": {"MUSE_UPGRADE_MODE": "1"},
        }

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
            An ``InvokeResult`` with the response text and zeroed usage. Muse's
            stdout stream carries no token counts; recovering them from the
            session log SASE names is the artifacts phase's job.

        Raises:
            subprocess.CalledProcessError: If the Muse CLI process fails. Exit
                code 2 is a CLI usage error rather than a model failure and is
                labeled as such in the raised diagnostics.
        """
        model = model_override if model_override else _TIER_TO_MODEL[model_tier]

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

        if model_tier == "large":
            extra_args_env = os.environ.get(
                "SASE_LLM_LARGE_ARGS", os.environ.get("SASE_MUSE_LARGE_ARGS")
            )
        else:
            extra_args_env = os.environ.get(
                "SASE_LLM_SMALL_ARGS", os.environ.get("SASE_MUSE_SMALL_ARGS")
            )

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

        while True:
            # The prompt goes through a 0o600 managed temp file rather than
            # argv or stdin, and is removed as soon as the cycle ends.
            prompt_file = _write_prompt_file(current_prompt)
            try:
                command_args = [
                    *base_args,
                    # SASE generates the session id rather than letting Muse
                    # pick one: it is the handle that locates the session log.
                    "--session-id",
                    str(uuid.uuid4()),
                    "--prompt-file",
                    prompt_file,
                ]

                if timer_context:
                    with timer_context:
                        content, stderr_content, return_code, usage = (
                            self._run_subprocess(command_args, suppress_output)
                        )
                        print()
                else:
                    content, stderr_content, return_code, usage = self._run_subprocess(
                        command_args, suppress_output
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
            return InvokeResult(content=accumulated_response, usage=total_usage)

    def _run_subprocess(
        self,
        args: list[str],
        suppress_output: bool,
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

        return stream_and_parse_muse_json_output(
            process, suppress_output=suppress_output
        )
