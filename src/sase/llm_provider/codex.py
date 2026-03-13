"""Codex (OpenAI CLI agent) LLM provider implementation."""

import os
import subprocess

from sase.rich_utils import gemini_timer

from ._subprocess import stream_and_parse_codex_json_output
from .base import LLMProvider
from .types import ModelTier

# Map model tiers to Codex model names
_TIER_TO_MODEL: dict[ModelTier, str] = {
    "large": "o3",
    "small": "o4-mini",
}


class CodexProvider(LLMProvider):
    """LLM provider that invokes the Codex CLI tool."""

    def resolve_model_name(self, model_tier: ModelTier = "large") -> str:
        """Return the Codex model name for the given tier."""
        return _TIER_TO_MODEL[model_tier]

    def invoke(
        self,
        prompt: str,
        *,
        model_tier: ModelTier,
        suppress_output: bool = False,
        model_override: str | None = None,
    ) -> str:
        """Invoke Codex CLI with the given prompt (normal mode only).

        Args:
            prompt: The preprocessed prompt to send.
            model_tier: Which model tier to use ("large" or "small").
            suppress_output: If True, suppress real-time output to console.
            model_override: If set, use this model name directly instead of
                mapping from ``model_tier``.

        Returns:
            The response text from Codex.

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

        if timer_context:
            with timer_context:
                response_content, stderr_content, return_code = self._run_subprocess(
                    base_args, prompt, suppress_output
                )
                print()
        else:
            response_content, stderr_content, return_code = self._run_subprocess(
                base_args, prompt, suppress_output
            )

        if return_code != 0:
            raise subprocess.CalledProcessError(
                return_code,
                base_args,
                output=response_content,
                stderr=stderr_content,
            )

        return response_content.strip()

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

        return stream_and_parse_codex_json_output(
            process, suppress_output=suppress_output
        )
