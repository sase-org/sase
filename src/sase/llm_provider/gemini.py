"""Gemini LLM provider implementation.

Supports two modes:
- Normal mode (``--yolo``): run Gemini CLI without approval.
- Plan mode (``--approval-mode=plan``): two-phase plan/implement flow
  triggered by the ``%plan`` directive.
"""

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from sase.rich_utils import gemini_timer

from ._subprocess import stream_process_output
from .base import LLMProvider
from .types import ModelTier

_DEFAULT_MODEL = "gemini-3-flash-preview"

# Poll interval for plan approval responses (seconds)
_POLL_INTERVAL = 0.5


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


def _save_response_as_plan(text: str) -> str:
    """Save response text as a plan file when no ``.md`` file exists on disk.

    Returns:
        Path to the saved plan file.
    """
    plans_dir = Path.home() / ".gemini" / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    plan_path = plans_dir / f"gemini_plan_{uuid.uuid4().hex[:8]}.md"
    plan_path.write_text(text, encoding="utf-8")
    return str(plan_path)


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
# Plan approval
# ---------------------------------------------------------------------------


def _handle_plan_approval(plan_file: str | None, session_id: str) -> str | None:
    """Handle plan approval flow.

    Creates a TUI notification via ``notify_plan_approval()``, then polls for
    the user's response.  Sends desktop notification and tmux bell.

    Returns the plan file path if approved, ``None`` if rejected or missing.
    """
    from sase.main.plan_approve_handler import is_auto_approve_active

    if is_auto_approve_active():
        return plan_file

    if not plan_file:
        return None

    response_dir = Path.home() / ".sase" / "plan_approval" / session_id
    response_dir.mkdir(parents=True, exist_ok=True)

    request_path = response_dir / "plan_request.json"
    response_path = response_dir / "plan_response.json"

    if response_path.exists():
        response_path.unlink()

    request_data = {
        "plan_file": plan_file,
        "session_id": session_id,
        "timestamp": time.time(),
    }
    with open(request_path, "w", encoding="utf-8") as f:
        json.dump(request_data, f, indent=2)

    from sase.notifications.senders import notify_plan_approval

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", ".")
    agent_cl_name = os.environ.get("SASE_AGENT_CL_NAME")
    agent_project_file = os.environ.get("SASE_AGENT_PROJECT_FILE")
    agent_timestamp = os.environ.get("SASE_AGENT_TIMESTAMP")
    notify_plan_approval(
        plan_file=plan_file,
        response_dir=str(response_dir),
        session_id=session_id,
        project_dir=project_dir,
        agent_cl_name=agent_cl_name,
        agent_project_file=agent_project_file,
        agent_timestamp=agent_timestamp,
    )

    # Desktop notification + tmux bell
    from sase.main.plan_approve_handler import (
        get_tmux_prefix,
        ring_tmux_bell,
        send_desktop_notification,
    )

    prefix = get_tmux_prefix()
    send_desktop_notification(
        f"{prefix} Plan Complete", "Plan ready for review in sase ace"
    )
    ring_tmux_bell()

    # Poll for response (blocks until the user acts)
    while True:
        if response_path.exists():
            try:
                with open(response_path, encoding="utf-8") as f:
                    response_data = json.load(f)

                if request_path.exists():
                    request_path.unlink()
                response_path.unlink()

                if response_data.get("action") == "approve":
                    return plan_file
                return None
            except (json.JSONDecodeError, OSError):
                pass

        time.sleep(_POLL_INTERVAL)


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
            "/google/bin/releases/gemini-cli/tools/gemini",
            "--yolo",
            "--model",
            model,
        ]

        timer_context = (
            gemini_timer("Waiting for Gemini") if not suppress_output else None
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

        Phase 1: Run with ``--approval-mode=plan``. The model generates a plan
        and exits (rc=0 or rc=2 from the hook denial).  We find the plan file
        on disk (or save the response text as a plan), then present it for
        approval.

        Phase 2 (on approval): Run with ``--yolo`` and the plan content as
        prompt, instructing the model to implement.
        """
        plan_args = [
            "/google/bin/releases/gemini-cli/tools/gemini",
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

            # Phase 1: planning
            if timer_context:
                with timer_context:
                    response_content, stderr_content, return_code = (
                        self._run_subprocess(plan_args, prompt, suppress_output)
                    )
                    print()
            else:
                response_content, stderr_content, return_code = self._run_subprocess(
                    plan_args, prompt, suppress_output
                )

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
                plan_file = _save_response_as_plan(response_content.strip())
            if not plan_file:
                raise RuntimeError(
                    "Gemini plan mode produced no plan file and no response text"
                )

            # Save plan to ~/.sase/plans/
            saved_plan_path = _save_plan_to_sase(plan_file)
            _write_plan_path_artifact(saved_plan_path)

            # Handle approval (blocks until user approves/rejects)
            approved = _handle_plan_approval(plan_file, session_id)
            if not approved:
                # Rejected — return plan text only
                return response_content.strip()

            # Phase 2: implement the approved plan
            impl_args = [
                "/google/bin/releases/gemini-cli/tools/gemini",
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

        # Stream output in real-time
        return stream_process_output(process, suppress_output=suppress_output)
