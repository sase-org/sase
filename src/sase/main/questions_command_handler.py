"""Handler for ``sase questions '<json>'`` CLI subcommand."""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import NoReturn


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
    3. Write .sase_questions_pending marker JSON to SASE_ARTIFACTS_DIR
    4. Install no-op SIGTERM handler
    5. Kill process group via SIGTERM
    """
    # Guard: must be running inside sase agent
    if not os.environ.get("SASE_AGENT"):
        print(
            "Error: 'sase questions' is only available inside sase"
            " (SASE_AGENT env var not set).",
            file=sys.stderr,
        )
        sys.exit(1)

    artifacts_dir = os.environ.get("SASE_ARTIFACTS_DIR")
    if not artifacts_dir:
        print(
            "Error: SASE_ARTIFACTS_DIR env var not set.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Parse and validate questions JSON
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

    # Write .sase_questions_pending marker JSON
    marker_path = Path(artifacts_dir) / ".sase_questions_pending"
    marker_data = {
        "questions": questions,
        "timestamp": time.time(),
    }
    with open(marker_path, "w", encoding="utf-8") as f:
        json.dump(marker_data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())

    # Install no-op SIGTERM handler so this process survives its own killpg
    signal.signal(signal.SIGTERM, signal.SIG_IGN)

    # Kill process group
    os.killpg(os.getpgrp(), signal.SIGTERM)
    sys.exit(0)
