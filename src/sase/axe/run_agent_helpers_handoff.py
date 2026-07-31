"""Handoff marker cleanup helpers for the agent runner."""

from __future__ import annotations

import json
from pathlib import Path

from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)


def normalize_handoff_interruption_state(artifacts_dir: str) -> None:
    """Normalize SIGTERM-induced failed state before plan/question handoff.

    Precondition: called only from ``_handle_killed_iteration`` after it has
    already confirmed the runner's own handoff SIGTERM caused the failure —
    ``was_killed()`` is true, ``has_user_kill_intent()`` is false, and a
    ``.sase_plan_pending`` / ``.sase_questions_pending`` marker predates the
    kill. Given that precondition, any failed agent step in this artifacts
    directory is by construction the handoff's doing, so this rewrites
    structurally instead of matching provider error text: provider CLIs
    surface the same SIGTERM inconsistently (``claude`` and ``codex`` exit
    ``-15``, while ``agy`` traps it and exits ``1`` with
    ``Error: timeout waiting for response``), so no text heuristic can cover
    every provider uniformly. Embedded ``bash`` / ``python`` post-steps are
    left untouched since they can fail for reasons unrelated to the SIGTERM.
    """
    state_path = Path(artifacts_dir) / "workflow_state.json"
    index_dirty = False

    try:
        with open(state_path, encoding="utf-8") as f:
            state_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        state_data = None

    if isinstance(state_data, dict):
        changed = False
        for step_data in state_data.get("steps", []):
            if isinstance(step_data, dict) and step_data.get("status") == "failed":
                step_data["status"] = "completed"
                step_data["error"] = None
                step_data["traceback"] = None
                changed = True

        if state_data.get("status") == "failed":
            state_data["status"] = "completed"
            state_data["error"] = None
            state_data["traceback"] = None
            changed = True

        if changed:
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(state_data, f, indent=2)
            index_dirty = True

    for marker_path in Path(artifacts_dir).glob("prompt_step_*.json"):
        try:
            with open(marker_path, encoding="utf-8") as f:
                marker_data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        if not isinstance(marker_data, dict):
            continue
        if marker_data.get("status") != "failed":
            continue
        if marker_data.get("step_type", "agent") != "agent":
            continue

        marker_data["status"] = "completed"
        marker_data["error"] = None
        marker_data["traceback"] = None
        try:
            with open(marker_path, "w", encoding="utf-8") as f:
                json.dump(marker_data, f, indent=2)
            index_dirty = True
        except OSError:
            continue

    if index_dirty:
        update_agent_artifact_index_for_marker_mutation(artifacts_dir)


_NON_TERMINAL_WORKFLOW_STATUSES = frozenset({"running", "waiting_hitl", "in_progress"})
_NON_TERMINAL_STEP_STATUSES = frozenset({"in_progress", "waiting_hitl"})


def finalize_handoff_artifacts_as_completed(artifacts_dir: str) -> None:
    """Finalize non-terminal planner artifacts as completed at handoff."""
    index_dirty = False
    state_path = Path(artifacts_dir) / "workflow_state.json"
    try:
        with open(state_path, encoding="utf-8") as f:
            state_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        state_data = None

    if isinstance(state_data, dict):
        changed = False
        for step_data in state_data.get("steps", []):
            if (
                isinstance(step_data, dict)
                and step_data.get("status") in _NON_TERMINAL_WORKFLOW_STATUSES
            ):
                step_data["status"] = "completed"
                if step_data.get("error") is not None:
                    step_data["error"] = None
                if step_data.get("traceback") is not None:
                    step_data["traceback"] = None
                changed = True

        if state_data.get("status") in _NON_TERMINAL_WORKFLOW_STATUSES:
            state_data["status"] = "completed"
            if state_data.get("error") is not None:
                state_data["error"] = None
            if state_data.get("traceback") is not None:
                state_data["traceback"] = None
            changed = True

        if changed:
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(state_data, f, indent=2)
            index_dirty = True

    for marker_path in Path(artifacts_dir).glob("prompt_step_*.json"):
        try:
            with open(marker_path, encoding="utf-8") as f:
                marker_data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        if not isinstance(marker_data, dict):
            continue
        if marker_data.get("status") not in _NON_TERMINAL_STEP_STATUSES:
            continue

        marker_data["status"] = "completed"
        if marker_data.get("error") is not None:
            marker_data["error"] = None
        if marker_data.get("traceback") is not None:
            marker_data["traceback"] = None
        try:
            with open(marker_path, "w", encoding="utf-8") as f:
                json.dump(marker_data, f, indent=2)
            index_dirty = True
        except OSError:
            continue

    if index_dirty:
        update_agent_artifact_index_for_marker_mutation(artifacts_dir)


def update_step_marker_chat_path(artifacts_dir: str, chat_path: str) -> None:
    """Set response_path on step markers missing it after a handoff chat save."""
    index_dirty = False
    for marker_path in Path(artifacts_dir).glob("prompt_step_*.json"):
        if "__" in marker_path.name:
            continue
        try:
            with open(marker_path, encoding="utf-8") as f:
                marker_data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(marker_data, dict):
            continue
        if marker_data.get("response_path") is not None:
            continue
        marker_data["response_path"] = chat_path
        try:
            with open(marker_path, "w", encoding="utf-8") as f:
                json.dump(marker_data, f, indent=2)
            index_dirty = True
        except OSError:
            continue
    if index_dirty:
        update_agent_artifact_index_for_marker_mutation(artifacts_dir)
