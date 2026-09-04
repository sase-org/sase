"""Projection between dismissed bundle JSON, SQLite rows, and summaries."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from sase.core.agent_archive_facade import (
    archive_key_from_bundle,
    capabilities_from_bundle,
    validate_archive_visibility,
)

from ._bundle_io import (
    display_filename,
    optional_int,
    optional_str,
    path_shard,
    required_str,
    string_or_default,
)
from ._models import DismissedBundleSummary


def summary_from_bundle(
    root: Path,
    path: Path,
    bundle: dict[str, Any],
) -> DismissedBundleSummary:
    """Build a summary row from a bundle JSON object."""

    raw_suffix = required_str(bundle, "raw_suffix")
    filename = display_filename(root, path)
    shard = path_shard(root, path)
    project_file = optional_str(bundle.get("project_file"))
    llm_provider = optional_str(bundle.get("llm_provider"))
    key = archive_key_from_bundle(bundle)
    capabilities = capabilities_from_bundle(bundle)
    has_archive_payload = (
        isinstance(bundle.get("archive_schema_version"), int)
        or isinstance(bundle.get("archive_payload_sha256"), str)
        or isinstance(bundle.get("archive_capabilities"), dict)
    )
    visibility = validate_archive_visibility(
        string_or_default(
            bundle.get("archive_visibility") if has_archive_payload else "hidden",
            "hidden",
        )
    )
    source_username = key.source_username if key is not None else None
    source_machine = key.source_machine if key is not None else None
    source_run_id = key.source_run_id if key is not None else None
    agent_id = (
        f"{source_username}.{source_machine}@{source_run_id}"
        if key is not None
        else f"legacy:{raw_suffix}"
    )
    start_time = optional_str(bundle.get("start_time"))
    stop_time = optional_str(bundle.get("stop_time"))
    project_name = _project_name_from_file(project_file)
    workflow = optional_str(bundle.get("workflow"))
    return DismissedBundleSummary(
        raw_suffix=raw_suffix,
        bundle_path=str(path),
        shard=shard,
        filename=filename,
        agent_id=agent_id,
        source_username=source_username,
        source_machine=source_machine,
        source_run_id=source_run_id,
        archive_visibility=visibility,
        archive_payload_sha256=optional_str(bundle.get("archive_payload_sha256"))
        or _archive_payload_hash(bundle),
        historically_viewable=capabilities.historically_viewable,
        durably_revivable=capabilities.durably_revivable,
        restartable=capabilities.restartable,
        missing_requirements=capabilities.missing_requirements,
        agent_type=string_or_default(bundle.get("agent_type"), "run"),
        cl_name=string_or_default(bundle.get("cl_name"), "unknown"),
        agent_name=optional_str(bundle.get("agent_name")),
        status=string_or_default(bundle.get("status"), "DONE"),
        start_time=start_time,
        stop_time=stop_time,
        dismissed_at=optional_str(bundle.get("dismissed_at")) or stop_time,
        revived_at=optional_str(bundle.get("revived_at")),
        times_revived=optional_int(bundle.get("times_revived")) or 0,
        project_file=project_file,
        project_name=project_name,
        model=optional_str(bundle.get("model")),
        runtime=workflow,
        llm_provider=llm_provider,
        vcs_provider=optional_str(bundle.get("vcs_provider")),
        workflow=workflow,
        is_workflow_child=_is_workflow_child(bundle),
        parent_timestamp=optional_str(bundle.get("parent_timestamp")),
        step_index=optional_int(bundle.get("step_index")),
        step_name=optional_str(bundle.get("step_name")),
        step_type=optional_str(bundle.get("step_type")),
        retry_of_timestamp=optional_str(bundle.get("retry_of_timestamp")),
        retried_as_timestamp=optional_str(bundle.get("retried_as_timestamp")),
        retry_chain_root_timestamp=optional_str(
            bundle.get("retry_chain_root_timestamp")
        ),
        retry_attempt=optional_int(bundle.get("retry_attempt")) or 0,
        meta_changespec=_meta_patch(bundle),  # legacy compatibility alias
    )


def summary_from_row(row: sqlite3.Row) -> DismissedBundleSummary:
    archive_visibility = optional_str(_row_value(row, "effective_archive_visibility"))
    if archive_visibility is None:
        archive_visibility = string_or_default(row["archive_visibility"], "hidden")
    revived_at = optional_str(_row_value(row, "effective_revived_at"))
    if revived_at is None:
        revived_at = optional_str(row["revived_at"])
    times_revived = optional_int(_row_value(row, "effective_times_revived"))
    if times_revived is None:
        times_revived = optional_int(row["times_revived"]) or 0
    return DismissedBundleSummary(
        raw_suffix=str(row["raw_suffix"]),
        bundle_path=str(row["bundle_path"]),
        shard=str(row["shard"]),
        filename=str(row["filename"]),
        agent_id=str(row["agent_id"]),
        source_username=optional_str(row["source_username"]),
        source_machine=optional_str(row["source_machine"]),
        source_run_id=optional_str(row["source_run_id"]),
        archive_visibility=archive_visibility,
        archive_payload_sha256=optional_str(row["archive_payload_sha256"]),
        historically_viewable=bool(row["historically_viewable"]),
        durably_revivable=bool(row["durably_revivable"]),
        restartable=bool(row["restartable"]),
        missing_requirements=_missing_requirements(row["missing_requirements"]),
        agent_type=str(row["agent_type"]),
        cl_name=str(row["cl_name"]),
        agent_name=optional_str(row["agent_name"]),
        status=str(row["status"]),
        start_time=optional_str(row["start_time"]),
        stop_time=optional_str(row["stop_time"]),
        dismissed_at=optional_str(row["dismissed_at"]),
        revived_at=revived_at,
        times_revived=times_revived,
        project_file=optional_str(row["project_file"]),
        project_name=optional_str(row["project_name"]),
        model=optional_str(row["model"]),
        runtime=optional_str(row["runtime"]),
        llm_provider=optional_str(row["llm_provider"]),
        vcs_provider=optional_str(row["vcs_provider"]),
        workflow=optional_str(row["workflow"]),
        is_workflow_child=bool(row["is_workflow_child"]),
        parent_timestamp=optional_str(row["parent_timestamp"]),
        step_index=optional_int(row["step_index"]),
        step_name=optional_str(row["step_name"]),
        step_type=optional_str(row["step_type"]),
        retry_of_timestamp=optional_str(row["retry_of_timestamp"]),
        retried_as_timestamp=optional_str(row["retried_as_timestamp"]),
        retry_chain_root_timestamp=optional_str(row["retry_chain_root_timestamp"]),
        retry_attempt=int(row["retry_attempt"]),
        meta_changespec=optional_str(row["meta_patch"]),  # legacy compatibility alias
    )


def _is_workflow_child(bundle: dict[str, Any]) -> bool:
    explicit = bundle.get("is_workflow_child")
    if isinstance(explicit, bool):
        return explicit
    return (
        bundle.get("parent_workflow") is not None
        or bundle.get("parent_timestamp") is not None
    )


def _meta_patch(bundle: dict[str, Any]) -> str | None:
    step_output = bundle.get("step_output")
    if not isinstance(step_output, dict):
        return None
    meta_patch = step_output.get("meta_patch")
    if meta_patch:
        return str(meta_patch).strip()
    meta_changespec = step_output.get(  # legacy compatibility alias
        "meta_changespec"
    )
    if meta_changespec:  # legacy compatibility alias
        return str(meta_changespec).strip()  # legacy compatibility alias
    meta_new_cl = step_output.get("meta_new_cl")
    if meta_new_cl:
        value = str(meta_new_cl).strip()
        paren_idx = value.rfind(" (")
        if paren_idx > 0:
            return value[:paren_idx].strip()
        return value
    return None


def _archive_payload_hash(bundle: dict[str, Any]) -> str:
    payload = dict(bundle)
    payload.pop("archive_payload_sha256", None)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _project_name_from_file(project_file: str | None) -> str | None:
    if not project_file:
        return None
    try:
        return Path(project_file).expanduser().parent.name or None
    except (OSError, RuntimeError, ValueError):
        return None


def _missing_requirements(value: object) -> tuple[str, ...]:
    if not isinstance(value, str) or not value:
        return ()
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return ()
    if not isinstance(decoded, list):
        return ()
    return tuple(str(item) for item in decoded if isinstance(item, str))


def _row_value(row: sqlite3.Row, key: str) -> object:
    return row[key] if key in row.keys() else None
