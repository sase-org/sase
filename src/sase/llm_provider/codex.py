"""Codex (OpenAI CLI agent) LLM provider implementation."""

from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from sase.env_contracts import SASE_ACTIVE_PROJECT_DIR_ENV
from sase.output import provider_timer

from ._effort_args import effort_cli_args
from ._hookspec import hookimpl
from ._subprocess import start_interrupt_monitor, stream_and_parse_codex_json_output
from .base import LLMProvider
from .types import InvokeResult, LLMInvocationOptions, ModelTier

if TYPE_CHECKING:
    from .retry_config import ProviderRetryConfig
    from .usage_limit_config import ProviderUsageLimitConfig

# Map model tiers to Codex model names
_TIER_TO_MODEL: dict[ModelTier, str] = {
    "large": "gpt-5.6-sol",
    "small": "codex-mini-latest",
}

# Reasoning-effort levels Codex honors via ``-c model_reasoning_effort=...``.
# Codex rejects ``none``/``max`` (epic sase-55 provider support matrix). The
# quoted value mirrors the ``SASE_CODEX_LARGE_ARGS`` escape hatch exactly.
_EFFORT_CLI_ARGS: dict[str, list[str]] = {
    level: ["-c", f'model_reasoning_effort="{level}"']
    for level in ("minimal", "low", "medium", "high", "xhigh")
}
_DISABLE_SHADOW_HOME_ENV = "SASE_CODEX_DISABLE_SHADOW_HOME"
_CODEX_PATH_ENV = "SASE_CODEX_PATH"


def _resolve_codex_executable() -> str:
    """Return the Codex executable SASE should launch."""
    explicit_path = os.environ.get(_CODEX_PATH_ENV)
    if explicit_path:
        return explicit_path

    path_result = shutil.which("codex")
    if path_result:
        return path_result

    nvm_bin = os.environ.get("NVM_BIN")
    if nvm_bin:
        nvm_codex = Path(nvm_bin) / "codex"
        if nvm_codex.exists():
            return str(nvm_codex)

    return "codex"


def _codex_executable_not_found_error(command: str) -> FileNotFoundError:
    """Build an actionable missing-Codex diagnostic."""
    return FileNotFoundError(
        "Unable to launch Codex CLI executable "
        f"{command!r}. Set SASE_CODEX_PATH to the Codex binary, ensure "
        "'codex' is discoverable on PATH, or set NVM_BIN so SASE can try "
        "NVM_BIN/codex."
    )


def _sase_codex_shadow_home_root() -> Path:
    """Return the root directory for SASE-managed Codex shadow homes."""
    return (Path.home() / ".cache" / "sase" / "codex_home").resolve(strict=False)


def is_sase_managed_codex_home(path: str | os.PathLike[str]) -> bool:
    """Return whether *path* points inside SASE's Codex shadow-home root."""
    candidate = Path(path).expanduser().resolve(strict=False)
    root = _sase_codex_shadow_home_root()
    return candidate == root or candidate.is_relative_to(root)


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


_WORKSPACE_ENV_VARS: tuple[str, ...] = ("SASE_GIT_WORKSPACE_DIR",)


def _workspace_env_value() -> str | None:
    """Return the first non-empty SASE workspace env var value, if any."""
    for name in _WORKSPACE_ENV_VARS:
        value = os.environ.get(name)
        if value:
            return value
    return None


def _resolve_codex_project_dir() -> str:
    """Resolve the project directory Codex hooks and fallbacks should inspect."""
    return (
        os.environ.get("CODEX_PROJECT_DIR")
        or os.environ.get(SASE_ACTIVE_PROJECT_DIR_ENV)
        or _workspace_env_value()
        or os.getcwd()
    )


def _real_codex_home() -> Path:
    """Return the user's real Codex home."""
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home and not is_sase_managed_codex_home(codex_home):
        return Path(codex_home).expanduser().resolve(strict=False)
    return Path.home() / ".codex"


def _path_exists_or_is_symlink(path: Path) -> bool:
    """Return whether a path exists or is present as a symlink."""
    return path.exists() or path.is_symlink()


def _link_home_agents_fallback(shadow_home: Path, real_home: Path) -> None:
    """Expose SASE's home AGENTS.md to Codex when no Codex-global file wins."""
    home_agents = Path.home() / "AGENTS.md"
    shadow_agents = shadow_home / "AGENTS.md"

    if not home_agents.exists():
        return
    if _path_exists_or_is_symlink(shadow_agents):
        return
    if _path_exists_or_is_symlink(real_home / "AGENTS.override.md"):
        return
    if _path_exists_or_is_symlink(shadow_home / "AGENTS.override.md"):
        return

    shadow_agents.symlink_to(home_agents)


def _create_shadow_codex_home(real_home: Path) -> Path:
    """Create a disposable CODEX_HOME with a copied config and linked state."""
    cache_root = _sase_codex_shadow_home_root()
    cache_root.mkdir(parents=True, exist_ok=True)

    shadow_home = cache_root / f"{os.getpid()}-{uuid.uuid4().hex}"
    shadow_home.mkdir(mode=0o700)

    if not real_home.exists():
        _link_home_agents_fallback(shadow_home, real_home)
        return shadow_home

    for source in real_home.iterdir():
        dest = shadow_home / source.name
        if source.name == "config.toml":
            if source.exists():
                shutil.copy2(source, dest)
            continue
        dest.symlink_to(source, target_is_directory=source.is_dir())

    _link_home_agents_fallback(shadow_home, real_home)
    return shadow_home


@contextmanager
def _codex_subprocess_env() -> Iterator[dict[str, str]]:
    """Yield an env for Codex, isolating config writes unless disabled."""
    if os.environ.get(_DISABLE_SHADOW_HOME_ENV) == "1":
        env = os.environ.copy()
        env["CODEX_PROJECT_DIR"] = _resolve_codex_project_dir()
        yield env
        return

    shadow_home = _create_shadow_codex_home(_real_codex_home())
    env = os.environ.copy()
    env["CODEX_HOME"] = str(shadow_home)
    env["CODEX_PROJECT_DIR"] = _resolve_codex_project_dir()
    try:
        yield env
    finally:
        shutil.rmtree(shadow_home, ignore_errors=True)


class CodexProvider(LLMProvider):
    """LLM provider that invokes the Codex CLI tool."""

    _pending_interrupt_message: str | None = None

    def resolve_model_name(self, model_tier: ModelTier = "large") -> str:
        """Return the Codex model name for the given tier."""
        return _TIER_TO_MODEL[model_tier]

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
        return [
            "gpt-5.6-sol",
            "gpt-5.5",
            "gpt-5.3-codex",
            "gpt-5.3-codex-spark",
            "codex-mini-latest",
            "o3",
            "o4-mini",
            "gpt-5.4",
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4o",
            "gpt-4o-mini",
        ]

    @hookimpl
    def llm_model_short_aliases(self) -> dict[str, str]:
        return {
            "codex-mini-latest": "mini",
            "gpt-5.6-sol": "gpt56sol",
            "gpt-5.5": "gpt55",
            "gpt-5.4": "gpt54",
            "gpt-5.3-codex-spark": "gpt53spark",
            "gpt-5.3-codex": "gpt53",
            "gpt-4.1": "gpt41",
            "gpt-4.1-mini": "gpt41m",
            "gpt-4o-mini": "gpt4om",
        }

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
            "docs_url": "https://developers.openai.com/codex/cli/",
            "self_update_argv": ["update"],
            "latest_version_package": "@openai/codex",
            "brew_package": "codex",
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

    def invocation_option_args(self, options: LLMInvocationOptions | None) -> list[str]:
        """Translate a resolved reasoning effort into ``-c`` config args."""
        return effort_cli_args(
            options, provider_label="Codex", supported=_EFFORT_CLI_ARGS
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
        model = model_override if model_override else _TIER_TO_MODEL[model_tier]

        base_args = [
            _resolve_codex_executable(),
            "exec",
            "--model",
            model,
            "--dangerously-bypass-approvals-and-sandbox",
            "--json",
            "--color",
            "never",
            "--skip-git-repo-check",
            "-",
        ]

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
        while True:
            if timer_context:
                with timer_context:
                    response_content, stderr_content, return_code = (
                        self._run_subprocess(base_args, current_prompt, suppress_output)
                    )
                    print()
            else:
                response_content, stderr_content, return_code = self._run_subprocess(
                    base_args, current_prompt, suppress_output
                )

            # Check for user interrupt before error handling
            if self._pending_interrupt_message is not None:
                user_msg = self._pending_interrupt_message
                self._pending_interrupt_message = None
                cycle += 1
                _log_interrupt(user_msg, cycle)
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
                raise subprocess.CalledProcessError(
                    return_code,
                    base_args,
                    output=response_content,
                    stderr=stderr_content,
                )

            accumulated_response = (
                accumulated_response + "\n\n" + response_content.strip()
            ).strip()
            return InvokeResult(content=accumulated_response)

    # ------------------------------------------------------------------
    # Subprocess runner
    # ------------------------------------------------------------------

    def _run_subprocess(
        self,
        args: list[str],
        prompt: str,
        suppress_output: bool,
    ) -> tuple[str, str, int]:
        """Run the Codex CLI subprocess.

        Args:
            args: Command-line arguments.
            prompt: Prompt to write to stdin.
            suppress_output: If True, suppress output.

        Returns:
            Tuple of (stdout_content, stderr_content, return_code).
        """
        with _codex_subprocess_env() as env:
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
                raise _codex_executable_not_found_error(args[0]) from exc

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

            return stream_and_parse_codex_json_output(
                process, suppress_output=suppress_output
            )
