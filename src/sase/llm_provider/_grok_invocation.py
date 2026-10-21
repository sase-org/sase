"""Grok invocation flow and ``--rules`` construction."""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from pathlib import Path

from sase.output import provider_timer

from ._effort_args import effort_cli_args
from ._grok_cli import GROK_RULES_ARGV_BYTE_LIMIT, resolve_grok_executable
from ._grok_subprocess import GrokSubprocessMixin
from .base import LLMProvider
from .instruction_delivery import current_instruction_delivery
from .types import InvokeResult, LLMInvocationError, LLMInvocationOptions, ModelTier

_EFFORT_CLI_ARGS: dict[str, list[str]] = {
    level: ["--effort", level] for level in ("low", "medium", "high", "xhigh")
}

GROK_SINGLE_TURN_DIRECTIVE = (
    "SASE single-turn instructions for Grok: this session is exactly one turn, "
    "and nothing can wake you after you end it. Notifications that arrive "
    '"in a new turn after your turn ends" — from background commands, '
    "background subagents, `monitor`, or `scheduler_create` — never reach "
    "you, and anything still running when you give your final response is "
    "lost. Run commands in the foreground: set `run_terminal_command`'s "
    "`block_until_ms` longer than the command takes, because the 30-second "
    "default moves slower commands to the background. If a command returns a "
    "task id instead of an exit code, it is still running, not done: call "
    "`get_command_or_subagent_output` with that task id and a `timeout_ms` "
    "until it reports an exit code. Call `spawn_subagent` with `background: "
    "false`, or wait on each `subagent_id` the same way. Handoff commands "
    "such as `sase monitor start`, `sase plan propose`, `sase pipe`, and "
    "`sase questions` can take up to a minute before they hand off; wait for "
    "the handoff command itself to exit. Never end your turn to wait."
)


def _grok_rules_text(cwd: Path | str | None = None) -> str:
    """Return the `--rules` payload for a Grok run from *cwd*.

    In SASE-managed projects this is the single-turn directive, a blank line,
    and the project root's ``AGENTS.md`` text exactly once. Elsewhere it is
    the directive alone. The file is read on every call. The home layer and
    ``CLAUDE.md`` are never included.
    """
    from sase.content_layout import discover_project_root
    from sase.feature_flags.managed import project_is_sase_managed

    start = Path(cwd).expanduser() if cwd is not None else None
    agents_path: Path | None = None
    if project_is_sase_managed(start):
        root = discover_project_root(start)
        if root is not None:
            candidate = root / "AGENTS.md"
            if candidate.is_file():
                agents_path = candidate
    if agents_path is None:
        return GROK_SINGLE_TURN_DIRECTIVE
    agents_text = agents_path.read_text(encoding="utf-8")
    rules = f"{GROK_SINGLE_TURN_DIRECTIVE}\n\n{agents_text}"
    size = len(rules.encode("utf-8"))
    if size > GROK_RULES_ARGV_BYTE_LIMIT:
        raise LLMInvocationError(
            "Grok (`grok`) --rules payload is too large for SASE's argv "
            f"transport: {size} UTF-8 bytes exceeds the "
            f"{GROK_RULES_ARGV_BYTE_LIMIT}-byte guard. The project "
            f"instructions file {agents_path} is too large to pass as one "
            "argv element (Linux rejects a single argv element above 128 "
            "KiB). Shrink that file."
        )
    return rules


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


class GrokInvocationMixin(GrokSubprocessMixin, LLMProvider):
    """Methods that build and run a Grok invocation."""

    _pending_interrupt_message: str | None = None

    def invocation_option_args(self, options: LLMInvocationOptions | None) -> list[str]:
        """Translate a resolved reasoning effort into ``--effort`` args."""
        return effort_cli_args(
            options, provider_label="Grok Build", supported=_EFFORT_CLI_ARGS
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
        model = (
            model_override if model_override else self.resolve_model_name(model_tier)
        )
        effort_args = self.invocation_option_args(options)

        if model_tier == "large":
            extra_args_env = os.environ.get(
                "SASE_LLM_LARGE_ARGS", os.environ.get("SASE_GROK_LARGE_ARGS")
            )
        else:
            extra_args_env = os.environ.get(
                "SASE_LLM_SMALL_ARGS", os.environ.get("SASE_GROK_SMALL_ARGS")
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
        suppress_output: bool,
    ) -> InvokeResult:
        while True:
            delivery = current_instruction_delivery()
            explicit_delivery = (
                delivery
                if delivery is not None and delivery.root.plan.status == "explicit"
                else None
            )
            rules_text: str
            if explicit_delivery is not None:
                explicit_rules = explicit_delivery.root.text
                if not explicit_rules:
                    explicit_delivery.report_fallback(
                        "root", "delivery_failed", "no delivered root text"
                    )
                    explicit_delivery = None
                else:
                    rules_size = len(explicit_rules.encode("utf-8"))
                    if rules_size > GROK_RULES_ARGV_BYTE_LIMIT:
                        explicit_delivery.report_fallback(
                            "root",
                            "oversize",
                            f"delivered rules are {rules_size} bytes; limit is "
                            f"{GROK_RULES_ARGV_BYTE_LIMIT}",
                        )
                        explicit_delivery = None
                    else:
                        rules_text = explicit_rules
            if explicit_delivery is None:
                rules_text = _grok_rules_text(os.getcwd())

            session_id = str(uuid.uuid4())
            if explicit_delivery is not None and delivery is not None:
                delivery.record_session(session_id)
            command_args = [
                resolve_grok_executable(),
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
                session_id,
                "--no-plan",
                "--no-ask-user",
                "--no-auto-update",
                "--no-leader",
                *effort_args,
            ]

            command_args.extend(["--rules", rules_text])

            run_kwargs = (
                {"env_overrides": {"GROK_MEMORY": "0"}}
                if explicit_delivery is not None
                else {}
            )

            if extra_args_env:
                for arg in extra_args_env.split():
                    command_args.append(arg)

            if not suppress_output:
                with provider_timer("Waiting for Grok"):
                    content, stderr_content, return_code, usage = self._run_subprocess(
                        command_args,
                        current_prompt,
                        suppress_output,
                        session_id=session_id,
                        cwd=os.getcwd(),
                        **run_kwargs,
                    )
                    print()
            else:
                content, stderr_content, return_code, usage = self._run_subprocess(
                    command_args,
                    current_prompt,
                    suppress_output,
                    session_id=session_id,
                    cwd=os.getcwd(),
                    **run_kwargs,
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
