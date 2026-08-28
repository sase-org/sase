"""Marker and workflow-state helpers for agent execution."""

from __future__ import annotations

import json
import os
from typing import Any

from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.patch_metadata import canonicalize_patch_metadata


def publish_phase_env(artifacts_dir: str) -> None:
    """Publish env vars that identify the current phase of the agent run.

    Both ``SASE_ARTIFACTS_DIR`` and ``SASE_AGENT_TIMESTAMP`` refer to the
    *current* phase. ``SASE_AGENT_ROOT_TIMESTAMP`` is set once by
    ``run_execution_loop`` and is intentionally left unchanged here.
    """
    from sase.ace.tui.models._timestamps import normalize_to_14_digit

    os.environ["SASE_ARTIFACTS_DIR"] = artifacts_dir
    basename = os.path.basename(artifacts_dir.rstrip("/"))
    os.environ["SASE_AGENT_TIMESTAMP"] = normalize_to_14_digit(basename) or basename


def write_done_marker_and_update_index(
    artifacts_dir: str,
    done_marker: dict[str, Any],
) -> str:
    """Write ``done.json`` and refresh the artifact index for that directory."""
    canonicalize_patch_metadata(done_marker)
    done_path = os.path.join(artifacts_dir, "done.json")
    with open(done_path, "w", encoding="utf-8") as f:
        json.dump(done_marker, f, indent=2)
    update_agent_artifact_index_for_marker_mutation(artifacts_dir)
    try:
        from sase.shells.settlement import (
            project_name_from_artifacts_dir,
            touch_shell_refresh_pulse,
        )

        touch_shell_refresh_pulse(project_name_from_artifacts_dir(artifacts_dir))
    except Exception:  # noqa: BLE001 - pulse must never fail the agent run
        pass
    return done_path


def short_pdf_source(source_path: str | None, workspace_dir: str) -> str:
    if not source_path:
        return ""
    try:
        return os.path.relpath(source_path, workspace_dir)
    except ValueError:
        return source_path


def _pdf_activity_from_status(pdf_status: dict[str, Any] | None) -> str | None:
    if not pdf_status:
        return None
    stage = pdf_status.get("stage")
    total = pdf_status.get("total")
    index = pdf_status.get("index")
    generated = pdf_status.get("generated")
    skipped = pdf_status.get("skipped")
    source = pdf_status.get("source_path")
    reason = pdf_status.get("reason")

    if stage in {"source_started", "engine_started"}:
        prefix = f"PDF {index}/{total}" if index and total else "PDF"
        return f"{prefix} {source}".strip()
    if stage == "source_succeeded":
        prefix = f"PDF done {index}/{total}" if index and total else "PDF done"
        return f"{prefix} {source}".strip()
    if stage in {"source_failed", "skipped"}:
        if reason:
            return f"PDFs skipped: {reason}"
        return "PDF skipped"
    if stage == "completed":
        if reason:
            return f"PDFs skipped: {reason}"
        if generated is not None and total is not None:
            label = f"PDFs done {generated}/{total}"
            if skipped:
                label += f" ({skipped} skipped)"
            return label
        return "PDFs done"
    if stage == "started":
        return "Preparing PDFs from Markdown..."
    return None


def update_workflow_pdf_status(
    artifacts_dir: str,
    pdf_status: dict[str, Any],
) -> None:
    state_path = os.path.join(artifacts_dir, "workflow_state.json")
    try:
        with open(state_path, encoding="utf-8") as f:
            state_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return
    if not isinstance(state_data, dict):
        return
    state_data["pdf_status"] = pdf_status
    activity = _pdf_activity_from_status(pdf_status)
    if activity:
        state_data["activity"] = activity
    else:
        state_data.pop("activity", None)
    try:
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state_data, f, indent=2)
        update_agent_artifact_index_for_marker_mutation(artifacts_dir)
    except OSError:
        pass


def clear_workflow_pdf_activity(artifacts_dir: str) -> None:
    state_path = os.path.join(artifacts_dir, "workflow_state.json")
    try:
        with open(state_path, encoding="utf-8") as f:
            state_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return
    if not isinstance(state_data, dict):
        return
    state_data.pop("activity", None)
    try:
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state_data, f, indent=2)
        update_agent_artifact_index_for_marker_mutation(artifacts_dir)
    except OSError:
        pass


_clear_workflow_pdf_activity = clear_workflow_pdf_activity
_publish_phase_env = publish_phase_env
_short_pdf_source = short_pdf_source
_update_workflow_pdf_status = update_workflow_pdf_status
_write_done_marker_and_update_index = write_done_marker_and_update_index
