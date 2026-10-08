"""Metadata and done-marker helpers for the run agent runner."""

import json
import os
from datetime import UTC, datetime
from typing import Any

from sase.axe.agent_meta import overlay_live_auto_keys, write_agent_meta_atomic
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.process_identity import process_identity_token
from sase.env_contracts import SASE_LAUNCH_SCRATCH_KEY_ENV


def persist_refreshed_clan_summary(
    artifacts_dir: str,
    agent_meta: dict[str, Any],
    clan_summary: str,
) -> dict[str, Any]:
    """Merge a refreshed clan summary into current disk and runner metadata."""
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    disk_meta: dict[str, Any] = {}
    try:
        with open(meta_path, encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            disk_meta = loaded
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass

    merged_meta = {**disk_meta, **agent_meta, "clan_summary": clan_summary}
    # Memory-wins merge must not resurrect auto state an ``A`` toggle
    # stripped from disk: the live on-disk auto keys win.
    overlay_live_auto_keys(artifacts_dir, merged_meta, disk_meta=disk_meta)
    write_agent_meta(artifacts_dir, merged_meta)
    agent_meta.update(merged_meta)
    return merged_meta


def _epoch_from_iso(value: object) -> float | None:
    """Return epoch seconds for an ISO 8601 timestamp string, else None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


def record_run_started_at(
    artifacts_dir: str,
    agent_meta: dict[str, Any],
    *,
    slot_wait_started_at: float | None = None,
) -> str:
    """Persist the execution-loop start timestamp if it has not been recorded.

    When first stamping ``run_started_at``, also stamp ``admission_latency_s``
    (``run_started_at`` minus ``wait_completed_at``, for runs that crossed a
    wait barrier) and ``runner_slot_wait_s`` (``run_started_at`` minus the
    instant the runner entered ``wait_for_runner_slot``). The disk-stamp
    short-circuit writes nothing new, keeping the stamp idempotent.
    """
    from datetime import UTC, datetime

    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    disk_meta: dict[str, Any] = {}
    try:
        with open(meta_path, encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            disk_meta = loaded
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass

    disk_run_started_at = disk_meta.get("run_started_at")
    if isinstance(disk_run_started_at, str) and disk_run_started_at:
        agent_meta["run_started_at"] = disk_run_started_at
        return disk_run_started_at

    memory_run_started_at = agent_meta.get("run_started_at")
    if isinstance(memory_run_started_at, str) and memory_run_started_at:
        run_started_at = memory_run_started_at
    else:
        run_started_at = datetime.now(UTC).isoformat()
        agent_meta["run_started_at"] = run_started_at

    merged_meta = {**disk_meta, **agent_meta, "run_started_at": run_started_at}
    run_started_epoch = _epoch_from_iso(run_started_at)
    if run_started_epoch is not None:
        wait_completed_epoch = _epoch_from_iso(merged_meta.get("wait_completed_at"))
        if wait_completed_epoch is not None:
            merged_meta["admission_latency_s"] = (
                run_started_epoch - wait_completed_epoch
            )
        if isinstance(slot_wait_started_at, (int, float)) and not isinstance(
            slot_wait_started_at, bool
        ):
            merged_meta["runner_slot_wait_s"] = run_started_epoch - float(
                slot_wait_started_at
            )
    # Memory-wins merge must not resurrect auto state an ``A`` toggle
    # stripped from disk: the live on-disk auto keys win.
    overlay_live_auto_keys(artifacts_dir, merged_meta, disk_meta=disk_meta)
    agent_meta.update(merged_meta)
    write_agent_meta(artifacts_dir, merged_meta)
    return run_started_at


def build_done_marker(
    cl_name: str,
    project_file: str,
    timestamp: str,
    artifacts_timestamp: str,
    workspace_num: int,
    workspace_dir: str,
    output_path: str,
    outcome: str,
    *,
    agent_name: str | None = None,
    agent_model: str | None = None,
    agent_llm_provider: str | None = None,
    agent_exec_llm_provider: str | None = None,
    agent_vcs_provider: str | None = None,
    agent_hidden: bool = False,
    response_path: str | None = None,
    step_output: dict[str, Any] | None = None,
    diff_path: str | None = None,
    plan_path: str | None = None,
    markdown_pdf_paths: list[str] | None = None,
    image_paths: list[str] | None = None,
    video_paths: list[str] | None = None,
    default_artifacts_persisted: bool = False,
    error: str | None = None,
    traceback_str: str | None = None,
    retry_metadata: dict[str, Any] | None = None,
    retried_as_timestamp: str | None = None,
    retry_chain_root_timestamp: str | None = None,
    retry_error_category: str | None = None,
    repeat_stopped: bool = False,
    stopped_by: str | None = None,
    finished_at: float | None = None,
    kill_source: str | None = None,
    kill_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a done marker dict for writing to done.json."""
    marker: dict[str, Any] = {
        "patch_name": cl_name,
        "cl_name": cl_name,
        "project_file": project_file,
        "timestamp": timestamp,
        "artifacts_timestamp": artifacts_timestamp,
        "outcome": outcome,
        "workspace_num": workspace_num,
        "workspace_dir": workspace_dir,
        "output_path": output_path,
        "finished_at": (
            datetime.now(UTC).timestamp() if finished_at is None else float(finished_at)
        ),
    }
    if agent_name:
        marker["name"] = agent_name
    if agent_model:
        marker["model"] = agent_model
    if agent_llm_provider:
        marker["llm_provider"] = agent_llm_provider
    if agent_exec_llm_provider:
        marker["exec_llm_provider"] = agent_exec_llm_provider
    if agent_vcs_provider:
        marker["vcs_provider"] = agent_vcs_provider
    if agent_hidden:
        marker["hidden"] = True
    # Completed outcome always includes result fields (even if None).
    if outcome == "completed":
        marker["response_path"] = response_path
        marker["step_output"] = step_output
        marker["diff_path"] = diff_path
        marker["plan_path"] = plan_path
        marker["markdown_pdf_paths"] = markdown_pdf_paths or []
        marker["image_paths"] = image_paths or []
        marker["video_paths"] = video_paths or []
        if default_artifacts_persisted:
            marker["default_artifacts_persisted"] = True
    elif response_path:
        marker["response_path"] = response_path
    # Failed outcome includes error details.
    if error:
        marker["error"] = error
    if traceback_str:
        marker["traceback"] = traceback_str
    if retry_metadata:
        marker["retry_metadata"] = retry_metadata
    # Spawn-on-retry: the failing parent records a forward pointer to its
    # retry child so the loader can build the retry-chain linkage without
    # opening agent_meta.json.
    if retried_as_timestamp:
        marker["retried_as_timestamp"] = retried_as_timestamp
    if retry_chain_root_timestamp:
        marker["retry_chain_root_timestamp"] = retry_chain_root_timestamp
    if retry_error_category:
        marker["retry_error_category"] = retry_error_category
    # Repeat-chain STOP: a successful skipped repeat slot keeps
    # ``outcome: "completed"`` (so the wait-check chop cascades it) but records
    # that it was stopped by a predecessor rather than actually executed.
    if repeat_stopped:
        marker["repeat_stopped"] = True
        if stopped_by:
            marker["stopped_by"] = stopped_by
    # Kill provenance is additive and only recorded for killed runs, so
    # lifecycle, retry, and UI consumers keying on ``outcome`` are unaffected.
    if kill_source:
        marker["kill_source"] = kill_source
        if kill_evidence:
            marker["kill_evidence"] = kill_evidence
    return marker


def record_stop_time(
    *artifacts_dirs: str | None,
    stopped_at: datetime | str | None = None,
) -> None:
    """Record stopped_at timestamp in agent_meta.json for each artifacts dir."""
    from datetime import UTC, datetime as dt_cls

    stopped_at_value = (
        stopped_at.isoformat()
        if isinstance(stopped_at, datetime)
        else stopped_at or dt_cls.now(UTC).isoformat()
    )
    for ad in set(artifacts_dirs):
        if ad is None:
            continue
        meta_p = os.path.join(ad, "agent_meta.json")
        try:
            with open(meta_p, encoding="utf-8") as f:
                meta_data = json.load(f)
            meta_data["stopped_at"] = stopped_at_value
            write_agent_meta(ad, meta_data)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass


def write_agent_meta(artifacts_dir: str, agent_meta: dict[str, Any]) -> None:
    pid = agent_meta.get("pid")
    if "process_identity" not in agent_meta and isinstance(pid, int):
        agent_meta["process_identity"] = process_identity_token(pid)
    # The scratch key is inherited by everything this runner launches; only the
    # runner itself may record it, never a TUI or CLI rewriting its meta.
    if (
        "launch_scratch_key" not in agent_meta
        and pid == os.getpid()
        and os.environ.get(SASE_LAUNCH_SCRATCH_KEY_ENV)
    ):
        agent_meta["launch_scratch_key"] = os.environ[SASE_LAUNCH_SCRATCH_KEY_ENV]
    write_agent_meta_atomic(
        artifacts_dir,
        agent_meta,
        index_updater=update_agent_artifact_index_for_marker_mutation,
    )
