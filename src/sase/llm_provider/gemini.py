"""Gemini LLM provider implementation.

Supports two modes:
- Normal mode (``--yolo``): run Gemini CLI without approval.
- Plan mode (``--approval-mode=plan``): two-phase plan/implement flow
  triggered by the ``%plan`` directive.
"""

import os
import subprocess
import time
import uuid
from pathlib import Path

from sase.rich_utils import gemini_timer

from ._plan_utils import (
    handle_plan_approval,
    save_plan_to_sase,
    save_response_as_plan,
    write_plan_path_artifact,
)
from ._subprocess import stream_process_output
from .base import LLMProvider
from .types import ModelTier

_DEFAULT_MODEL = "gemini-3-flash-preview"


def _gemini_bin() -> str:
    """Return the path to the Gemini CLI binary."""
    return os.environ.get("SASE_GEMINI_PATH", "gemini")


# ---------------------------------------------------------------------------
# Plan file helpers
# ---------------------------------------------------------------------------


def _find_gemini_plan_file(after: float | None = None) -> str | None:
    """Find the most recently modified ``.md`` plan file in Gemini directories.

    Args:
        after: If set, only consider files modified after this timestamp.
            Used to filter out stale plan files from previous runs.
    """
    search_dirs = [
        Path.home() / ".gemini" / "plans",
        Path.home() / ".gemini",
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


# ---------------------------------------------------------------------------
# Provider class
# ---------------------------------------------------------------------------


def _log_interrupt(message: str, cycle: int) -> None:
    """Append an entry to the interrupt log in the artifacts directory."""
    import json

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


class GeminiProvider(LLMProvider):
    """LLM provider that invokes Google's Gemini CLI tool."""

    _pending_interrupt_message: str | None = None

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

        When ``SASE_AGENT_PLAN_MODE`` is set, runs a two-phase flow:
        Phase 1 with ``--approval-mode=plan`` to generate the plan, then
        Phase 2 with ``--yolo`` to implement the approved plan.

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

        if plan_mode:
            return self._invoke_plan_mode(prompt, suppress_output, model)

        # Normal (non-plan) mode
        base_args = [
            _gemini_bin(),
            "--yolo",
            "--model",
            model,
        ]

        timer_context = (
            gemini_timer("Waiting for Gemini") if not suppress_output else None
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
                accumulated_response += response_content
                # Gemini has no session persistence — reconstruct context
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

            return (accumulated_response + response_content).strip()

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

        Phase 1: Run with ``--approval-mode=plan``. The model generates a plan
        and exits (rc=0 or rc=2 from the hook denial).  We find the plan file
        on disk (or save the response text as a plan), then present it for
        approval.

        Phase 2 (on approval): Run with ``--yolo`` and the plan content as
        prompt, instructing the model to implement.
        """
        plan_args = [
            _gemini_bin(),
            "--approval-mode=plan",
            "--model",
            model,
        ]

        session_id = str(uuid.uuid4())
        start_time = time.time()

        # Set env var so the plan-approve hook knows to deny (external approval)
        os.environ["SASE_PLAN_EXTERNAL_APPROVAL"] = "1"
        try:
            timer_context = (
                gemini_timer("Waiting for Gemini (planning)")
                if not suppress_output
                else None
            )

            # Phase 1: planning (with interrupt support)
            current_plan_prompt = prompt
            plan_cycle = 0
            accumulated_plan_response = ""

            while True:
                if timer_context:
                    with timer_context:
                        response_content, stderr_content, return_code = (
                            self._run_subprocess(
                                plan_args, current_plan_prompt, suppress_output
                            )
                        )
                        print()
                else:
                    response_content, stderr_content, return_code = (
                        self._run_subprocess(
                            plan_args, current_plan_prompt, suppress_output
                        )
                    )

                # Check for user interrupt before error handling
                if self._pending_interrupt_message is not None:
                    user_msg = self._pending_interrupt_message
                    self._pending_interrupt_message = None
                    plan_cycle += 1
                    _log_interrupt(user_msg, plan_cycle)
                    accumulated_plan_response += response_content
                    current_plan_prompt = (
                        f"{prompt}\n\n"
                        f"--- Your Previous Response ---\n"
                        f"{accumulated_plan_response}\n\n"
                        f"--- User Follow-up ---\n{user_msg}"
                    )
                    continue

                break  # No interrupt — proceed to plan validation

            response_content = accumulated_plan_response + response_content

            # Accept rc=0 (normal exit) or rc=2 (hook denial = plan captured)
            if return_code not in (0, 2):
                raise subprocess.CalledProcessError(
                    return_code,
                    plan_args,
                    output=response_content,
                    stderr=stderr_content,
                )

            # Find the plan file (filter out stale files from before this run)
            plan_file = _find_gemini_plan_file(after=start_time)
            if not plan_file and response_content.strip():
                plan_file = save_response_as_plan(response_content.strip(), "gemini")
            if not plan_file:
                raise RuntimeError(
                    "Gemini plan mode produced no plan file and no response text"
                )

            # Save plan to ~/.sase/plans/
            saved_plan_path = save_plan_to_sase(plan_file)
            write_plan_path_artifact(saved_plan_path)

            # Handle approval (blocks until user approves/rejects)
            approved = handle_plan_approval(plan_file, session_id)
            if not approved:
                # Rejected — return plan text only
                return response_content.strip()

            # Phase 2: implement the approved plan
            impl_args = [
                _gemini_bin(),
                "--yolo",
                "--model",
                model,
            ]

            plan_content = saved_plan_path.read_text(encoding="utf-8")
            impl_prompt = (
                f"{plan_content}\n\n"
                "The above plan has been reviewed and approved. "
                "Implement it now."
            )

            original_impl_prompt = impl_prompt
            accumulated_impl_response = ""
            impl_cycle = 0

            while True:
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

                # Check for user interrupt before error handling
                if self._pending_interrupt_message is not None:
                    user_msg = self._pending_interrupt_message
                    self._pending_interrupt_message = None
                    impl_cycle += 1
                    _log_interrupt(user_msg, impl_cycle)
                    accumulated_impl_response += impl_content
                    impl_prompt = (
                        f"{original_impl_prompt}\n\n"
                        f"--- Your Previous Response ---\n"
                        f"{accumulated_impl_response}\n\n"
                        f"--- User Follow-up ---\n{user_msg}"
                    )
                    continue

                if impl_rc != 0:
                    raise subprocess.CalledProcessError(
                        impl_rc,
                        impl_args,
                        output=impl_content,
                        stderr=impl_stderr,
                    )

                accumulated_impl_response += impl_content
                break

            return (
                response_content.strip() + "\n\n" + accumulated_impl_response.strip()
            ).strip()
        finally:
            os.environ.pop("SASE_PLAN_EXTERNAL_APPROVAL", None)

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

        # Interrupt monitor: watch for interrupt_request.json from TUI
        artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
        if artifacts_dir:
            import json
            import threading

            interrupt_path = Path(artifacts_dir) / "interrupt_request.json"

            def _monitor_interrupt() -> None:
                while process.poll() is None:
                    if interrupt_path.exists():
                        try:
                            data = json.loads(
                                interrupt_path.read_text(encoding="utf-8")
                            )
                            self._pending_interrupt_message = data.get("message")
                            interrupt_path.unlink(missing_ok=True)
                            process.terminate()
                        except (OSError, json.JSONDecodeError):
                            pass
                        return
                    time.sleep(1.0)

            threading.Thread(target=_monitor_interrupt, daemon=True).start()

        # Stream output in real-time
        return stream_process_output(process, suppress_output=suppress_output)
