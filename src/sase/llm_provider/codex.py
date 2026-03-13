"""Codex (OpenAI CLI agent) LLM provider implementation.

Supports two modes:
- Normal mode: run Codex CLI with full permissions.
- Plan mode: two-phase plan/implement flow triggered by the
  ``SASE_AGENT_PLAN_MODE`` environment variable.
"""

import os
import subprocess
import time
import uuid
from pathlib import Path

from sase.rich_utils import gemini_timer

from ._plan_utils import (
    append_plan_feedback_log,
    handle_plan_approval,
    read_plan_feedback,
    save_plan_to_sase,
    save_response_as_plan,
    write_plan_path_artifact,
)
from ._subprocess import stream_and_parse_codex_json_output
from .base import LLMProvider
from .types import ModelTier

# Map model tiers to Codex model names
_TIER_TO_MODEL: dict[ModelTier, str] = {
    "large": "gpt-5.4",
    "small": "o4-mini",
}

# Maximum number of plan feedback retry rounds before giving up
_MAX_PLAN_FEEDBACK_RETRIES = 5


def _find_codex_plan_file(after: float | None = None) -> str | None:
    """Find the most recently modified ``.md`` plan file in Codex directories.

    Args:
        after: If set, only consider files modified after this timestamp.
    """
    search_dirs = [
        Path.home() / ".codex" / "plans",
        Path.home() / ".codex",
    ]
    md_files: list[Path] = []
    for d in search_dirs:
        if d.is_dir():
            md_files.extend(d.glob("*.md"))
    if after is not None:
        md_files = [f for f in md_files if f.stat().st_mtime > after]
    if not md_files:
        return None
    return str(max(md_files, key=lambda f: f.stat().st_mtime))


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
        """Invoke Codex CLI with the given prompt.

        When ``SASE_AGENT_PLAN_MODE`` is set, runs a two-phase flow:
        Phase 1 with read-only sandbox to generate the plan, then
        Phase 2 with full permissions to implement the approved plan.

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
        plan_mode = bool(os.environ.get("SASE_AGENT_PLAN_MODE"))

        if plan_mode:
            return self._invoke_plan_mode(prompt, suppress_output, model)

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

    # ------------------------------------------------------------------
    # Plan mode two-phase flow
    # ------------------------------------------------------------------

    def _invoke_plan_mode(
        self,
        prompt: str,
        suppress_output: bool,
        model: str,
    ) -> str:
        """Execute the two-phase plan/implement flow.

        Phase 1: Run with read-only sandbox. The model generates a plan.
        We capture the plan text via ``--output-last-message``, on-disk plan
        files, or streamed response text.  The plan is presented for
        approval with feedback retry (up to 5 rounds).

        Phase 2 (on approval): Run with full permissions and the plan
        content as prompt, instructing the model to implement.
        """
        import tempfile

        session_id = str(uuid.uuid4())
        start_time = time.time()

        current_prompt = prompt
        response_content = ""
        saved_plan_path = Path()

        for retry_round in range(_MAX_PLAN_FEEDBACK_RETRIES + 1):
            # Phase 1: planning with read-only sandbox
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=False
            ) as tmp:
                output_file = tmp.name

            plan_args = [
                "codex",
                "exec",
                "--model",
                model,
                "--ask-for-approval",
                "on-request",
                "--sandbox",
                "read-only",
                "--json",
                "--color",
                "never",
                "--skip-git-repo-check",
                "--output-last-message",
                output_file,
                "-",
            ]

            timer_context = (
                gemini_timer("Waiting for Codex (planning)")
                if not suppress_output
                else None
            )

            if timer_context:
                with timer_context:
                    response_content, stderr_content, return_code = (
                        self._run_subprocess(plan_args, current_prompt, suppress_output)
                    )
                    print()
            else:
                response_content, stderr_content, return_code = self._run_subprocess(
                    plan_args, current_prompt, suppress_output
                )

            if return_code != 0:
                raise subprocess.CalledProcessError(
                    return_code,
                    plan_args,
                    output=response_content,
                    stderr=stderr_content,
                )

            # Plan text capture fallback chain
            plan_file: str | None = None

            # 1. --output-last-message temp file
            try:
                output_text = Path(output_file).read_text(encoding="utf-8").strip()
                if output_text:
                    plan_file = save_response_as_plan(output_text, "codex")
            except OSError:
                pass
            finally:
                try:
                    Path(output_file).unlink()
                except OSError:
                    pass

            # 2. Search codex plan directories
            if not plan_file:
                plan_file = _find_codex_plan_file(after=start_time)

            # 3. Streamed response text
            if not plan_file and response_content.strip():
                plan_file = save_response_as_plan(response_content.strip(), "codex")

            # 4. Give up
            if not plan_file:
                raise RuntimeError(
                    "Codex plan mode produced no plan file and no response text"
                )

            # Save plan to ~/.sase/plans/
            saved_plan_path = save_plan_to_sase(plan_file)
            write_plan_path_artifact(saved_plan_path)

            # Handle approval (blocks until user approves/rejects)
            approved = handle_plan_approval(plan_file, session_id)
            if approved:
                break  # Plan approved — proceed to phase 2

            # Rejected — check for feedback
            approval_dir = Path.home() / ".sase" / "plan_approval" / session_id
            feedback = read_plan_feedback(approval_dir)
            if not feedback:
                # Rejected without feedback — return plan text only
                return response_content.strip()

            append_plan_feedback_log(feedback, retry_round)
            plan_content = saved_plan_path.read_text(encoding="utf-8")
            current_prompt = (
                f"{prompt}\n\n"
                f"--- Previous Plan ---\n{plan_content}\n"
                f"--- User Feedback ---\n{feedback}\n\n"
                "Please revise the plan based on the feedback "
                "above and resubmit it."
            )

            # Generate new session_id for the retry
            session_id = str(uuid.uuid4())
            start_time = time.time()
        else:
            # Exhausted retries without approval
            return response_content.strip()

        # Phase 2: implement the approved plan
        plan_content = saved_plan_path.read_text(encoding="utf-8")
        impl_prompt = (
            f"{plan_content}\n\n"
            "The above plan has been reviewed and approved. "
            "Implement it now."
        )

        impl_args = [
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

        if not suppress_output:
            with gemini_timer("Implementing plan"):
                impl_content, impl_stderr, impl_rc = self._run_subprocess(
                    impl_args, impl_prompt, suppress_output
                )
                print()
        else:
            impl_content, impl_stderr, impl_rc = self._run_subprocess(
                impl_args, impl_prompt, suppress_output
            )

        if impl_rc != 0:
            raise subprocess.CalledProcessError(
                impl_rc,
                impl_args,
                output=impl_content,
                stderr=impl_stderr,
            )

        return (response_content.strip() + "\n\n" + impl_content.strip()).strip()

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

        return stream_and_parse_codex_json_output(
            process, suppress_output=suppress_output
        )
