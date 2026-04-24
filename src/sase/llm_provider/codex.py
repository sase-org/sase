"""Codex (OpenAI CLI agent) LLM provider implementation."""

import os
import subprocess
from pathlib import Path

from sase.output import gemini_timer

from ._hookspec import hookimpl
from ._subprocess import start_interrupt_monitor, stream_and_parse_codex_json_output
from .base import LLMProvider
from .types import InvokeResult, ModelTier

# Map model tiers to Codex model names
_TIER_TO_MODEL: dict[ModelTier, str] = {
    "large": "gpt-5.5",
    "small": "codex-mini-latest",
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
    def llm_resolve_model_name(self, model_tier: ModelTier) -> str:
        return self.resolve_model_name(model_tier)

    @hookimpl
    def llm_known_model_names(self) -> list[str]:
        return [
            "gpt-5.5",
            "gpt-5.3-codex",
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
    def llm_invoke(
        self,
        prompt: str,
        model_tier: ModelTier,
        suppress_output: bool,
        model_override: str | None,
    ) -> InvokeResult:
        return self.invoke(
            prompt,
            model_tier=model_tier,
            suppress_output=suppress_output,
            model_override=model_override,
        )

    def invoke(
        self,
        prompt: str,
        *,
        model_tier: ModelTier,
        suppress_output: bool = False,
        model_override: str | None = None,
    ) -> InvokeResult:
        """Invoke Codex CLI with the given prompt.

        Args:
            prompt: The preprocessed prompt to send.
            model_tier: Which model tier to use ("large" or "small").
            suppress_output: If True, suppress real-time output to console.
            model_override: If set, use this model name directly instead of
                mapping from ``model_tier``.

        Returns:
            An ``InvokeResult`` with the response text (usage is ``None``).

        Raises:
            subprocess.CalledProcessError: If the Codex CLI process fails.
        """
        model = model_override if model_override else _TIER_TO_MODEL[model_tier]

        base_args = [
            "codex",
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
            gemini_timer("Waiting for Codex") if not suppress_output else None
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

        return stream_and_parse_codex_json_output(
            process, suppress_output=suppress_output
        )
