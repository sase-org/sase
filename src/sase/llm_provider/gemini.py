"""Gemini LLM provider implementation.

Supports two modes:
- Normal mode (``--yolo``): run Gemini CLI without approval.
- Plan mode (``--approval-mode=plan``): two-phase plan/implement flow
  triggered by the ``%plan`` directive.
"""

import ast
import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from sase.rich_utils import gemini_timer

from ._subprocess import stream_process_output
from .base import LLMProvider
from .types import ModelTier

_DEFAULT_MODEL = "gemini-3.1-pro-preview"

# Marker string in Gemini API proxy log lines
_GEMINI_LOG_MARKER = "Sending partial reply: "

# Poll interval for plan approval / question responses (seconds)
_POLL_INTERVAL = 0.5


# ---------------------------------------------------------------------------
# Gemini log parsing helpers
# ---------------------------------------------------------------------------


def _resolve_gemini_log_path() -> Path:
    """Resolve the path to the Gemini API proxy log file."""
    tmp_dir = os.environ.get("SASE_GEMINI_CLI_TMP") or os.environ.get("TMP") or "/tmp"
    return Path(tmp_dir) / "gemini_api_proxy.par.INFO"


def _parse_function_call_from_log_line(line: str) -> dict[str, Any] | None:
    """Parse a Gemini API proxy log line for a ``functionCall``.

    Returns the ``functionCall`` dict ``{"name": ..., "args": ...}`` if
    found, or ``None``.
    """
    pos = line.find(_GEMINI_LOG_MARKER)
    if pos == -1:
        return None

    byte_literal = line[pos + len(_GEMINI_LOG_MARKER) :].rstrip()
    try:
        raw = ast.literal_eval(byte_literal)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        data = json.loads(raw)
    except (ValueError, SyntaxError, json.JSONDecodeError):
        return None

    for candidate in data.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            if "functionCall" in part:
                return part["functionCall"]
    return None


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
# Plan approval and ask_user handling
# ---------------------------------------------------------------------------


def _handle_plan_approval(plan_file: str | None, session_id: str) -> str | None:
    """Handle plan approval flow.

    Returns the plan file path if approved, ``None`` if rejected or missing.
    """
    # Auto-approve when %approve directive is active
    if os.environ.get("SASE_AGENT_AUTO_APPROVE"):
        return plan_file

    if not plan_file:
        return None

    # Set up response directory (same layout as Claude plan approval handler)
    response_dir = Path.home() / ".sase" / "plan_approval" / session_id
    response_dir.mkdir(parents=True, exist_ok=True)

    request_path = response_dir / "plan_request.json"
    response_path = response_dir / "plan_response.json"

    # Clean stale response file
    if response_path.exists():
        response_path.unlink()

    # Write request file
    request_data = {
        "plan_file": plan_file,
        "session_id": session_id,
        "timestamp": time.time(),
    }
    with open(request_path, "w", encoding="utf-8") as f:
        json.dump(request_data, f, indent=2)

    # Create sase notification
    from sase.notifications.senders import notify_plan_approval

    agent_cl_name = os.environ.get("SASE_AGENT_CL_NAME")
    agent_project_file = os.environ.get("SASE_AGENT_PROJECT_FILE")
    agent_timestamp = os.environ.get("SASE_AGENT_TIMESTAMP")
    notify_plan_approval(
        plan_file=plan_file,
        response_dir=str(response_dir),
        session_id=session_id,
        agent_cl_name=agent_cl_name,
        agent_project_file=agent_project_file,
        agent_timestamp=agent_timestamp,
    )

    # Poll for response (blocks until user acts)
    while True:
        if response_path.exists():
            try:
                with open(response_path, encoding="utf-8") as f:
                    response_data = json.load(f)

                # Clean up
                if request_path.exists():
                    request_path.unlink()
                response_path.unlink()

                if response_data.get("action") == "approve":
                    return plan_file
                return None
            except (json.JSONDecodeError, OSError):
                pass

        time.sleep(_POLL_INTERVAL)


def _handle_ask_user(
    process: subprocess.Popen[str],
    func_args: dict[str, Any],
) -> None:
    """Handle ``ask_user`` function call via notification + stdin write-back."""
    questions = func_args.get("questions", [])
    if not questions:
        return

    # Auto-select first option when %approve directive is active
    if os.environ.get("SASE_AGENT_AUTO_APPROVE"):
        answers: list[dict[str, Any]] = []
        for q in questions:
            question_text = q.get("question", "")
            options = q.get("options", [])
            selected = [options[0].get("label", "")] if options else []
            answers.append({"question": question_text, "selected": selected})
        _write_answer_to_stdin(process, answers)
        return

    # Create response directory
    question_id = str(uuid.uuid4())
    response_dir = Path.home() / ".sase" / "user_question" / question_id
    response_dir.mkdir(parents=True, exist_ok=True)

    request_path = response_dir / "question_request.json"
    response_path = response_dir / "question_response.json"

    # Write request file
    request_data: dict[str, Any] = {
        "session_id": question_id,
        "timestamp": time.time(),
        "questions": questions,
    }
    with open(request_path, "w", encoding="utf-8") as f:
        json.dump(request_data, f, indent=2)

    # Create sase notification
    from sase.notifications.senders import notify_user_question

    first_question = ""
    if questions:
        first_question = questions[0].get("question", "")
    if len(first_question) > 80:
        first_question = first_question[:77] + "..."

    agent_cl_name = os.environ.get("SASE_AGENT_CL_NAME")
    agent_project_file = os.environ.get("SASE_AGENT_PROJECT_FILE")
    agent_timestamp = os.environ.get("SASE_AGENT_TIMESTAMP")
    notify_user_question(
        response_dir=str(response_dir),
        session_id=question_id,
        notes=first_question,
        agent_cl_name=agent_cl_name,
        agent_project_file=agent_project_file,
        agent_timestamp=agent_timestamp,
    )

    # Poll for response
    while True:
        if process.poll() is not None:
            return  # Process terminated; give up

        if response_path.exists():
            try:
                with open(response_path, encoding="utf-8") as f:
                    response_data = json.load(f)

                # Clean up
                if request_path.exists():
                    request_path.unlink()
                response_path.unlink()

                _write_answer_to_stdin(process, response_data.get("answers", []))
                return
            except (json.JSONDecodeError, OSError):
                pass

        time.sleep(_POLL_INTERVAL)


def _write_answer_to_stdin(
    process: subprocess.Popen[str],
    answers: list[dict[str, Any]],
) -> None:
    """Write formatted answers back to Gemini CLI via stdin.

    NOTE: This requires stdin to remain open (not closed after the initial
    prompt).  If Gemini CLI does not support mid-session stdin writes, the
    answer can be included in the Phase 2 implementation context instead.
    """
    if not process.stdin:
        return

    lines: list[str] = []
    for answer in answers:
        question = answer.get("question", "")
        selected = answer.get("selected", [])
        custom = answer.get("custom_feedback", "")
        lines.append(f"Q: {question}")
        if selected:
            lines.append(f"A: {', '.join(selected)}")
        if custom:
            lines.append(f"Note: {custom}")

    answer_text = "\n".join(lines)
    try:
        process.stdin.write(answer_text + "\n")
        process.stdin.flush()
    except (OSError, BrokenPipeError):
        pass  # Process may have terminated


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
        Phase 1 with ``--approval-mode=plan`` (monitors log for
        ``exit_plan_mode``), then Phase 2 with ``--yolo`` to implement
        the approved plan.

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

        if plan_mode:
            return self._invoke_plan_mode(
                base_args, prompt, suppress_output, model, timer_context
            )

        # Normal (non-plan) mode
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
        base_args: list[str],
        prompt: str,
        suppress_output: bool,
        model: str,
        timer_context: Any,
    ) -> str:
        """Execute the two-phase plan/implement flow."""
        # Phase 1: planning
        if timer_context:
            with timer_context:
                result = self._run_plan_subprocess(base_args, prompt, suppress_output)
                print()
        else:
            result = self._run_plan_subprocess(base_args, prompt, suppress_output)

        response_content, stderr_content, return_code, approved_plan = result

        if approved_plan:
            # Save plan to ~/.sase/plans/
            saved_plan_path = _save_plan_to_sase(approved_plan)
            _write_plan_path_artifact(saved_plan_path)

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

            if timer_context:
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

            # Combine phase 1 + phase 2 response text
            response_content = response_content.strip() + "\n\n" + impl_content.strip()
        elif return_code != 0:
            raise subprocess.CalledProcessError(
                return_code,
                base_args,
                output=response_content,
                stderr=stderr_content,
            )

        return response_content.strip()

    # ------------------------------------------------------------------
    # Subprocess runners
    # ------------------------------------------------------------------

    def _run_plan_subprocess(
        self,
        args: list[str],
        prompt: str,
        suppress_output: bool,
    ) -> tuple[str, str, int, str | None]:
        """Run Gemini CLI with plan mode log monitoring.

        Starts a background thread that tails the Gemini API proxy log for
        ``exit_plan_mode`` and ``ask_user`` function calls.

        Returns:
            Tuple of ``(stdout, stderr, return_code, approved_plan_file)``.
            ``approved_plan_file`` is the path to the plan file when the plan
            was detected and approved by the user, or ``None``.
        """
        process = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        session_id = str(uuid.uuid4())
        approved_plan: list[str | None] = [None]  # thread-safe via list

        # Write prompt but keep stdin open for ask_user responses
        if process.stdin:
            process.stdin.write(prompt)
            process.stdin.flush()

        def _monitor() -> None:
            log_path = _resolve_gemini_log_path()

            # Wait for the log file to appear (up to 60 s)
            for _ in range(60):
                if process.poll() is not None or log_path.exists():
                    break
                time.sleep(1.0)

            if not log_path.exists() or process.poll() is not None:
                return

            with open(log_path, encoding="utf-8", errors="replace") as f:
                f.seek(0, 2)  # seek to end — only new entries

                while process.poll() is None:
                    line = f.readline()
                    if not line:
                        time.sleep(0.5)
                        continue

                    func_call = _parse_function_call_from_log_line(line)
                    if not func_call:
                        continue

                    name = func_call.get("name", "").removeprefix("default_api:")

                    if name == "exit_plan_mode":
                        plan_file = _find_gemini_plan_file()
                        result = _handle_plan_approval(plan_file, session_id)
                        if result:
                            approved_plan[0] = result
                        try:
                            process.terminate()
                        except OSError:
                            pass
                        return

                    if name == "ask_user":
                        _handle_ask_user(process, func_call.get("args", {}))

        threading.Thread(target=_monitor, daemon=True).start()

        # Stream output in real-time
        stdout_content, stderr_content, return_code = stream_process_output(
            process, suppress_output=suppress_output
        )

        return stdout_content, stderr_content, return_code, approved_plan[0]

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
