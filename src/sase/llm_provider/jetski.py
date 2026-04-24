"""Jetski (Google successor to Gemini CLI) LLM provider implementation."""

import os
import subprocess
from pathlib import Path

from sase.output import gemini_timer

from ._hookspec import hookimpl
from ._subprocess import start_interrupt_monitor, stream_process_output
from .base import LLMProvider
from .types import InvokeResult, ModelTier

# Default install path for the Jetski CLI binary (from Jetski install docs).
# Users can override with SASE_JETSKI_PATH, or place ``jetski-cli`` on PATH.
_DEFAULT_BINARY = "/google/bin/releases/jetski-devs/tools/cli"

# TODO(open-question-3): replace with canonical Jetski model name once the
# Cloudtop spike confirms it.
_DEFAULT_MODEL = "jetski-default"


def _jetski_bin() -> str:
    """Return the path to the Jetski CLI binary.

    Resolution order:
    1. ``SASE_JETSKI_PATH`` env var.
    2. ``/google/bin/releases/jetski-devs/tools/cli`` if present on disk.
    3. ``"jetski-cli"`` (PATH lookup, for users who aliased the long path).
    """
    env_path = os.environ.get("SASE_JETSKI_PATH")
    if env_path:
        return env_path
    if Path(_DEFAULT_BINARY).exists():
        return _DEFAULT_BINARY
    return "jetski-cli"


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


class JetskiProvider(LLMProvider):
    """LLM provider that invokes Google's Jetski CLI tool."""

    _pending_interrupt_message: str | None = None

    def resolve_model_name(self, model_tier: ModelTier = "large") -> str:  # noqa: ARG002
        """Return the Jetski model name.

        TODO(open-question-3): map ``model_tier`` to tier-specific models once
        canonical Jetski model names are confirmed.
        """
        return _DEFAULT_MODEL

    @hookimpl
    def llm_provider_name(self) -> str:
        return "jetski"

    @hookimpl
    def llm_resolve_model_name(self, model_tier: ModelTier) -> str:
        return self.resolve_model_name(model_tier)

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
        model_tier: ModelTier,  # noqa: ARG002
        suppress_output: bool = False,
        model_override: str | None = None,  # noqa: ARG002
    ) -> InvokeResult:
        """Invoke Jetski CLI with the given prompt.

        Args:
            prompt: The preprocessed prompt to send.
            model_tier: Unused pending tier mapping (open question 3).
            suppress_output: If True, suppress real-time output to console.
            model_override: Accepted for interface parity but currently ignored.
                Jetski CLI has no ``--model`` flag; model selection happens
                interactively via the ``/model`` slash command, which persists
                to ``~/.gemini/jetski/cli/settings.json``.

        Returns:
            An ``InvokeResult`` with the response text (usage is ``None``).

        Raises:
            subprocess.CalledProcessError: If the Jetski CLI process fails.
        """
        timer_context = (
            gemini_timer("Waiting for Jetski") if not suppress_output else None
        )

        current_prompt = prompt
        accumulated_response = ""
        cycle = 0

        while True:
            # Jetski CLI convention (per go/jetski-cli-getting-started):
            #   jetski-cli -p "<prompt>"
            # The prompt is a positional argument after ``-p``; stdin is NOT
            # read in ``-p`` mode. ``--model`` is not a CLI flag — model
            # selection is the interactive ``/model`` slash command, which
            # persists to ``~/.gemini/jetski/cli/settings.json``.
            base_args = [_jetski_bin(), "-p", current_prompt]

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

            # Check for user interrupt before error handling.
            if self._pending_interrupt_message is not None:
                user_msg = self._pending_interrupt_message
                self._pending_interrupt_message = None
                cycle += 1
                _log_interrupt(user_msg, cycle)
                accumulated_response += response_content
                # TODO(open-question-4): if Jetski ``-p`` supports
                # ``--continue`` / ``--conversation <id>``, switch to
                # Claude-style session resume. Until confirmed, fall back to
                # Gemini-style context rebuild.
                current_prompt = (
                    f"{prompt}\n\n"
                    f"--- Your Previous Response ---\n{accumulated_response}\n\n"
                    f"--- User Follow-up ---\n{user_msg}"
                )
                continue

            if return_code != 0:
                raise subprocess.CalledProcessError(
                    return_code,
                    base_args,
                    output=response_content,
                    stderr=stderr_content,
                )

            return InvokeResult(
                content=(accumulated_response + response_content).strip()
            )

    # ------------------------------------------------------------------
    # Subprocess runner
    # ------------------------------------------------------------------

    def _run_subprocess(
        self,
        args: list[str],
        prompt: str,  # noqa: ARG002
        suppress_output: bool,
    ) -> tuple[str, str, int]:
        """Run the Jetski CLI subprocess.

        Args:
            args: Command-line arguments; includes the prompt as the
                positional token after ``-p``.
            prompt: Unused — retained as a parameter so tests can patch this
                method and inspect the prompt independently of argv.
            suppress_output: If True, suppress output.

        Returns:
            Tuple of (stdout_content, stderr_content, return_code).
        """
        # Jetski CLI reads the prompt from argv (positional after ``-p``),
        # not from stdin. ``stdin=PIPE`` is kept for signature symmetry with
        # the other providers and costs nothing when left empty-and-closed.
        process = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        start_interrupt_monitor(
            process,
            on_interrupt=lambda msg: setattr(self, "_pending_interrupt_message", msg),
        )

        # TODO(open-question-1): Jetski output-format parsing. If ``-p`` emits
        # JSON/NDJSON, swap this for a dedicated parser and populate
        # ``InvokeResult.usage`` (open question 5).
        return stream_process_output(
            process, suppress_output=suppress_output, clean_ansi=True
        )
