"""Deterministic fake LLM provider backed by the bundled ``fakey`` CLI."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.output import provider_timer

from ._effort_args import effort_cli_args
from ._hookspec import hookimpl
from ._subprocess import start_interrupt_monitor, stream_process_output
from ._subprocess_artifacts import write_usage_artifact
from .base import LLMProvider
from .types import InvokeResult, LLMInvocationOptions, ModelTier

if TYPE_CHECKING:
    from .retry_config import ProviderRetryConfig


_TIER_TO_MODEL: dict[ModelTier, str] = {
    "large": "fakey-large",
    "small": "fakey-small",
}
_FAKEY_PATH_ENV = "SASE_FAKEY_PATH"
_EFFORT_CLI_ARGS = {
    level: ("--effort", level)
    for level in ("none", "minimal", "low", "medium", "high", "xhigh", "max")
}


def _fakey_bin() -> str:
    """Return the bundled fakey executable, honoring the test override."""
    return os.environ.get(_FAKEY_PATH_ENV, "fakey")


def _fakey_executable_not_found_error(command: str) -> FileNotFoundError:
    return FileNotFoundError(
        "Unable to launch the bundled fakey executable "
        f"{command!r}. Reinstall SASE, set SASE_FAKEY_PATH to the fakey binary, "
        "or ensure 'fakey' is discoverable on PATH."
    )


def _log_interrupt(message: str | None, cycle: int) -> None:
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        return
    log_path = Path(artifacts_dir) / "interrupt_log.jsonl"
    try:
        with log_path.open("a", encoding="utf-8") as stream:
            json.dump(
                {"message": message, "timestamp": time.time(), "cycle": cycle},
                stream,
            )
            stream.write("\n")
    except OSError:
        pass


def _extract_usage(content: str) -> tuple[str, dict[str, int] | None]:
    """Strip and parse a final ``FAKEY-USAGE`` protocol line."""
    lines = content.splitlines(keepends=True)
    if not lines or not lines[-1].startswith("FAKEY-USAGE: "):
        return content, None

    payload = lines[-1][len("FAKEY-USAGE: ") :].strip()
    try:
        decoded: Any = json.loads(payload)
    except json.JSONDecodeError:
        return content, None
    if not isinstance(decoded, dict):
        return content, None

    usage = {
        str(key): int(value)
        for key, value in decoded.items()
        if isinstance(value, int | float) and not isinstance(value, bool)
    }
    return "".join(lines[:-1]), usage


class FakeyProvider(LLMProvider):
    """Invoke SASE's deterministic fake agent as a normal LLM provider."""

    _pending_interrupt_message: str | None = None

    def resolve_model_name(self, model_tier: ModelTier = "large") -> str:
        return _TIER_TO_MODEL[model_tier]

    @hookimpl
    def llm_provider_name(self) -> str:
        return "fakey"

    @hookimpl
    def llm_provider_short_name(self) -> str:
        return "fky"

    @hookimpl
    def llm_resolve_model_name(self, model_tier: ModelTier) -> str:
        return self.resolve_model_name(model_tier)

    @hookimpl
    def llm_known_model_names(self) -> list[str]:
        return ["fakey-large", "fakey-small"]

    @hookimpl
    def llm_model_short_aliases(self) -> dict[str, str]:
        return {"fakey-large": "fakeyl", "fakey-small": "fakeys"}

    @hookimpl
    def llm_skill_deploy_subpath(self) -> None:
        return None

    @hookimpl
    def llm_cli_status_color(self) -> str:
        return "#FF5FAF"

    @hookimpl
    def llm_autodetect_priority(self) -> int:
        # Fakey is installed with SASE, so it must remain behind every real CLI.
        return 1000

    @hookimpl
    def llm_autodetect_cli_name(self) -> str:
        return "fakey"

    @hookimpl
    def llm_auth_evidence(self) -> dict[str, object]:
        return {
            "credential_paths": [],
            "api_key_env_vars": [],
            "auth_not_required": True,
        }

    @hookimpl
    def llm_install_metadata(self) -> dict[str, object]:
        return {
            "manager": "bundled",
            "package": "sase",
            "scope": "environment",
            "display_name": "Fakey",
        }

    @hookimpl
    def llm_default_retry_config(self) -> ProviderRetryConfig:
        from .retry_config import _RETRY_CONTINUATION_NUDGE, ProviderRetryConfig

        return ProviderRetryConfig(
            max_retries=3,
            error_patterns=["FAKEY-RETRYABLE"],
            wait_times=[0],
            continuation_prompt=_RETRY_CONTINUATION_NUDGE,
            preserve_workspace=True,
        )

    def invocation_option_args(self, options: LLMInvocationOptions | None) -> list[str]:
        return effort_cli_args(
            options,
            provider_label="Fakey",
            supported=_EFFORT_CLI_ARGS,
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
        model = model_override or _TIER_TO_MODEL[model_tier]
        base_args = [_fakey_bin(), "--model", model]
        base_args.extend(self.invocation_option_args(options))

        if model_tier == "large":
            extra_args = os.environ.get(
                "SASE_LLM_LARGE_ARGS", os.environ.get("SASE_FAKEY_LARGE_ARGS")
            )
        else:
            extra_args = os.environ.get(
                "SASE_LLM_SMALL_ARGS", os.environ.get("SASE_FAKEY_SMALL_ARGS")
            )
        if extra_args:
            base_args.extend(extra_args.split())

        timer_context = (
            provider_timer("Waiting for Fakey") if not suppress_output else None
        )
        current_prompt = prompt
        accumulated_response = ""
        total_usage: dict[str, int] | None = None
        cycle = 0

        while True:
            if timer_context:
                with timer_context:
                    content, stderr_content, return_code = self._run_subprocess(
                        base_args, current_prompt, suppress_output
                    )
                    print()
            else:
                content, stderr_content, return_code = self._run_subprocess(
                    base_args, current_prompt, suppress_output
                )

            content, usage = _extract_usage(content)
            if usage is not None:
                if total_usage is None:
                    total_usage = {}
                for key, value in usage.items():
                    total_usage[key] = total_usage.get(key, 0) + value

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
            if total_usage is not None:
                write_usage_artifact(total_usage)
            return InvokeResult(content=accumulated_response, usage=total_usage)

    def _run_subprocess(
        self,
        args: list[str],
        prompt: str,
        suppress_output: bool,
    ) -> tuple[str, str, int]:
        try:
            process = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except FileNotFoundError as exc:
            raise _fakey_executable_not_found_error(args[0]) from exc

        if process.stdin:
            process.stdin.write(prompt)
            process.stdin.close()

        start_interrupt_monitor(
            process,
            on_interrupt=lambda msg: setattr(self, "_pending_interrupt_message", msg),
        )
        return stream_process_output(process, suppress_output=suppress_output)
