"""Gemini LLM provider implementation.

Supports two modes:
- Normal mode (``--yolo``): run Gemini CLI without approval.
- Plan mode (``--approval-mode=plan``): plan/implement flow triggered by the
  ``%plan`` directive.  Gemini CLI hooks (configured in ``~/.gemini/settings.json``)
  handle ``exit_plan_mode`` and ``ask_user`` tool calls by invoking
  ``sase plan-approve`` and ``sase user-question``, which create TUI notifications
  and poll for user responses.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

from sase.rich_utils import gemini_timer

from ._subprocess import stream_process_output
from .base import LLMProvider
from .types import ModelTier

_DEFAULT_MODEL = "gemini-3.1-pro-preview"


# ---------------------------------------------------------------------------
# Plan file helpers
# ---------------------------------------------------------------------------


def _find_gemini_plan_file() -> str | None:
    """Find the most recently modified ``.md`` plan file in Gemini directories."""
    search_dirs = [
        Path.home() / ".gemini" / "plans",
        Path.home() / ".gemini",
    ]
    md_files: list[Path] = []
    for d in search_dirs:
        if d.is_dir():
            md_files.extend(d.glob("*.md"))
    if not md_files:
        return None
    return str(max(md_files, key=lambda f: f.stat().st_mtime))


def _save_plan_to_sase(plan_file: str) -> Path:
    """Copy a plan file to ``~/.sase/plans/`` for persistence."""
    sase_plans_dir = Path.home() / ".sase" / "plans"
    sase_plans_dir.mkdir(parents=True, exist_ok=True)
    src = Path(plan_file)
    dest = sase_plans_dir / src.name
    if dest.exists():
        stem = src.stem
        suffix = src.suffix
        counter = 1
        while dest.exists():
            dest = sase_plans_dir / f"{stem}_{counter}{suffix}"
            counter += 1
    shutil.copy2(src, dest)
    return dest


def _write_plan_path_artifact(saved_plan_path: Path) -> None:
    """Write ``plan_path.json`` so agent runner can thread it to ``done.json``."""
    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if artifacts_dir:
        plan_path_file = Path(artifacts_dir) / "plan_path.json"
        plan_path_file.write_text(json.dumps({"plan_path": str(saved_plan_path)}))


# ---------------------------------------------------------------------------
# Provider class
# ---------------------------------------------------------------------------


class GeminiProvider(LLMProvider):
    """LLM provider that invokes Google's Gemini CLI tool."""

    def resolve_model_name(self, model_tier: ModelTier = "large") -> str:  # noqa: ARG002
        """Return the Gemini model name."""
        return _DEFAULT_MODEL

    def invoke(
        self,
        prompt: str,
        *,
        model_tier: ModelTier,  # noqa: ARG002
        suppress_output: bool = False,
        model_override: str | None = None,
    ) -> str:
        """Invoke Gemini CLI with the given prompt.

        When ``SASE_AGENT_PLAN_MODE`` is set, runs with
        ``--approval-mode=plan``.  Gemini CLI hooks handle plan approval
        and user questions; after approval Gemini continues to implementation
        within the same process.

        Args:
            prompt: The preprocessed prompt to send.
            model_tier: Unused. Accepted for interface compatibility.
            suppress_output: If True, suppress real-time output to console.
            model_override: If set, use this model instead of the default.

        Returns:
            The response text from Gemini.

        Raises:
            subprocess.CalledProcessError: If the Gemini CLI process fails.
        """
        model = model_override or _DEFAULT_MODEL
        plan_mode = bool(os.environ.get("SASE_AGENT_PLAN_MODE"))

        # Build base command arguments
        if plan_mode:
            base_args = [
                "/google/bin/releases/gemini-cli/tools/gemini",
                "--approval-mode=plan",
                "--model",
                model,
            ]
        else:
            base_args = [
                "/google/bin/releases/gemini-cli/tools/gemini",
                "--yolo",
                "--model",
                model,
            ]

        timer_context = (
            gemini_timer("Waiting for Gemini") if not suppress_output else None
        )

        # Run subprocess (plan mode hooks handle approval internally)
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

        # For plan mode, find and save the plan file written during planning
        if plan_mode:
            plan_file = _find_gemini_plan_file()
            if plan_file:
                saved_plan_path = _save_plan_to_sase(plan_file)
                _write_plan_path_artifact(saved_plan_path)

        return response_content.strip()

    # ------------------------------------------------------------------
    # Subprocess runner
    # ------------------------------------------------------------------

    def _run_subprocess(
        self,
        args: list[str],
        prompt: str,
        suppress_output: bool,
    ) -> tuple[str, str, int]:
        """Run the Gemini CLI subprocess.

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

        # Stream output in real-time
        return stream_process_output(process, suppress_output=suppress_output)
