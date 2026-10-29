"""Handler for ``sase questions '<json>'`` CLI subcommand."""

from __future__ import annotations

import json
import sys
from typing import NoReturn

from sase.agent.pending_handoff import QUESTIONS_PENDING_MARKER
from sase.agent.pending_handoff_write import (
    PendingHandoffError,
    handoff_guard,
    write_pending_handoff_marker,
)
from sase.main.utils import kill_agent_runner_group

_STAGED_MESSAGE = (
    "Staged questions handoff. Nothing starts until this turn ends; "
    "finish with `/sase_final`."
)


def _validate_questions(questions: list[dict]) -> None:  # type: ignore[type-arg]
    """Validate questions JSON schema.

    Raises ValueError with a descriptive message on invalid input.
    """
    if not isinstance(questions, list) or len(questions) == 0:
        raise ValueError("questions must be a non-empty list")

    for i, q in enumerate(questions):
        if not isinstance(q, dict):
            raise ValueError(f"question[{i}] must be an object")
        if "question" not in q or not isinstance(q["question"], str):
            raise ValueError(f"question[{i}] must have a 'question' string field")
        if "options" in q:
            if not isinstance(q["options"], list):
                raise ValueError(f"question[{i}].options must be a list")
            for j, opt in enumerate(q["options"]):
                if not isinstance(opt, dict):
                    raise ValueError(f"question[{i}].options[{j}] must be an object")
                if "label" not in opt or not isinstance(opt["label"], str):
                    raise ValueError(
                        f"question[{i}].options[{j}] must have a 'label' string"
                    )
        if "multiSelect" in q and not isinstance(q["multiSelect"], bool):
            raise ValueError(f"question[{i}].multiSelect must be a boolean")


def handle_questions_command(questions_json: str) -> NoReturn:
    """Ask the user questions (used by /sase_questions skill).

    1. Guard: verify SASE_AGENT and SASE_ARTIFACTS_DIR env vars
    2. Parse and validate questions JSON
    3. With ``staged_handoffs`` on, write the staged record and exit 0.
       Otherwise write ``.sase_questions_pending`` and SIGTERM the runner.
    """
    try:
        artifacts_dir = handoff_guard(command="sase questions")
    except PendingHandoffError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    from sase.agent.staged_handoff import (
        StagedHandoffError,
        acquire_staging_reservation,
        release_staging_reservation,
        staged_handoffs_enabled,
    )

    use_staged_handoffs = staged_handoffs_enabled()
    reservation_id: str | None = None
    if use_staged_handoffs:
        try:
            reservation_id = acquire_staging_reservation(
                artifacts_dir=artifacts_dir,
                command="sase questions",
            )
        except StagedHandoffError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

    try:
        _handle_questions_after_guard(
            questions_json,
            artifacts_dir=artifacts_dir,
            use_staged_handoffs=use_staged_handoffs,
            reservation_id=reservation_id,
        )
    finally:
        if reservation_id is not None:
            release_staging_reservation(
                reservation_id,
                artifacts_dir=artifacts_dir,
            )


def _handle_questions_after_guard(
    questions_json: str,
    *,
    artifacts_dir: str,
    use_staged_handoffs: bool,
    reservation_id: str | None,
) -> NoReturn:
    """Parse, validate, and stage or kill after the one-handoff reservation."""
    try:
        questions = json.loads(questions_json)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        _validate_questions(questions)
    except ValueError as e:
        print(f"Error: Invalid questions schema: {e}", file=sys.stderr)
        sys.exit(1)

    if use_staged_handoffs:
        from sase.agent.staged_handoff import (
            StagedHandoffError,
            build_questions_staged_record,
            write_staged_handoff,
        )

        try:
            write_staged_handoff(
                build_questions_staged_record(questions=questions),
                artifacts_dir=artifacts_dir,
                command="sase questions",
                reservation_id=reservation_id,
            )
        except StagedHandoffError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        print(_STAGED_MESSAGE)
        sys.exit(0)

    try:
        write_pending_handoff_marker(
            QUESTIONS_PENDING_MARKER,
            {"questions": questions},
            artifacts_dir=artifacts_dir,
        )
    except PendingHandoffError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    # Kill the agent runner's process group (which includes the claude
    # subprocess).  We cannot use our own process group because Claude Code
    # spawns Bash-tool subprocesses in an isolated process group — the
    # SIGTERM would never reach `claude` or the agent runner.
    kill_agent_runner_group(artifacts_dir)
