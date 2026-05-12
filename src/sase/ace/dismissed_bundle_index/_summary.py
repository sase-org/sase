"""Projection between dismissed bundle JSON, SQLite rows, and summaries."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from ._bundle_io import (
    agent_id_for_bundle,
    display_filename,
    nonnegative_int_or_default,
    optional_int,
    optional_str,
    path_shard,
    positive_int_or_default,
    required_str,
    string_or_default,
)
from ._models import (
    DEFAULT_ARCHIVE_REVISION,
    DismissedBundleSummary,
    ERROR_MESSAGE_EXCERPT_CHARS,
    LEGACY_BUNDLE_SCHEMA_VERSION,
)


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
    return DismissedBundleSummary(
        agent_id=agent_id_for_bundle(bundle),
        raw_suffix=raw_suffix,
        bundle_path=str(path),
        shard=shard,
        filename=filename,
        archive_revision=positive_int_or_default(
            bundle.get("archive_revision"), DEFAULT_ARCHIVE_REVISION
        ),
        bundle_schema_version=nonnegative_int_or_default(
            bundle.get("bundle_schema_version"), LEGACY_BUNDLE_SCHEMA_VERSION
        ),
        agent_type=string_or_default(bundle.get("agent_type"), "run"),
        cl_name=string_or_default(bundle.get("cl_name"), "unknown"),
        agent_name=optional_str(bundle.get("agent_name")),
        status=string_or_default(bundle.get("status"), "DONE"),
        start_time=optional_str(bundle.get("start_time")),
        stop_time=optional_str(bundle.get("stop_time")),
        dismissed_at=_dismissed_at(bundle, path),
        revived_at=optional_str(bundle.get("revived_at")),
        times_revived=nonnegative_int_or_default(bundle.get("times_revived"), 0),
        project_file=project_file,
        project_name=_project_name(project_file),
        model=optional_str(bundle.get("model")),
        llm_provider=llm_provider,
        runtime=_runtime(bundle, llm_provider),
        vcs_provider=optional_str(bundle.get("vcs_provider")),
        workflow=optional_str(bundle.get("workflow")),
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
        meta_changespec=_meta_changespec(bundle),
        cost_usd_micros=optional_int(bundle.get("cost_usd_micros")),
        input_tokens=_usage_int(bundle, "input_tokens"),
        output_tokens=_usage_int(bundle, "output_tokens"),
        error_message_excerpt=_error_message_excerpt(bundle),
    )


def summary_from_row(row: sqlite3.Row) -> DismissedBundleSummary:
    return DismissedBundleSummary(
        agent_id=str(row["agent_id"]),
        raw_suffix=str(row["raw_suffix"]),
        bundle_path=str(row["bundle_path"]),
        shard=str(row["shard"]),
        filename=str(row["filename"]),
        archive_revision=int(row["archive_revision"]),
        bundle_schema_version=int(row["bundle_schema_version"]),
        agent_type=str(row["agent_type"]),
        cl_name=str(row["cl_name"]),
        agent_name=optional_str(row["agent_name"]),
        status=str(row["status"]),
        start_time=optional_str(row["start_time"]),
        stop_time=optional_str(row["stop_time"]),
        dismissed_at=optional_str(row["dismissed_at"]),
        revived_at=optional_str(row["revived_at"]),
        times_revived=int(row["times_revived"]),
        project_file=optional_str(row["project_file"]),
        project_name=optional_str(row["project_name"]),
        model=optional_str(row["model"]),
        llm_provider=optional_str(row["llm_provider"]),
        runtime=optional_str(row["runtime"]),
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
        meta_changespec=optional_str(row["meta_changespec"]),
        cost_usd_micros=optional_int(row["cost_usd_micros"]),
        input_tokens=optional_int(row["input_tokens"]),
        output_tokens=optional_int(row["output_tokens"]),
        error_message_excerpt=optional_str(row["error_message_excerpt"]),
    )


def _dismissed_at(bundle: dict[str, Any], path: Path) -> str | None:
    explicit = optional_str(bundle.get("dismissed_at"))
    if explicit:
        return explicit
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat()
    except OSError:
        return None


def _project_name(project_file: str | None) -> str | None:
    if not project_file:
        return None
    parent_name = Path(project_file).parent.name
    if parent_name:
        return parent_name
    stem = Path(project_file).stem
    return stem or None


def _runtime(bundle: dict[str, Any], llm_provider: str | None) -> str | None:
    return optional_str(bundle.get("runtime")) or llm_provider


def _usage_int(bundle: dict[str, Any], key: str) -> int | None:
    direct = optional_int(bundle.get(key))
    if direct is not None:
        return direct
    usage = bundle.get("usage")
    if isinstance(usage, dict):
        return optional_int(usage.get(key))
    return None


def _error_message_excerpt(bundle: dict[str, Any]) -> str | None:
    value = optional_str(bundle.get("error_message"))
    if not value:
        value = optional_str(bundle.get("error_traceback"))
    if not value:
        return None
    return value[:ERROR_MESSAGE_EXCERPT_CHARS]


def _is_workflow_child(bundle: dict[str, Any]) -> bool:
    explicit = bundle.get("is_workflow_child")
    if isinstance(explicit, bool):
        return explicit
    return (
        bundle.get("parent_workflow") is not None
        or bundle.get("parent_timestamp") is not None
    )


def _meta_changespec(bundle: dict[str, Any]) -> str | None:
    step_output = bundle.get("step_output")
    if not isinstance(step_output, dict):
        return None
    meta_changespec = step_output.get("meta_changespec")
    if meta_changespec:
        return str(meta_changespec).strip()
    meta_new_cl = step_output.get("meta_new_cl")
    if meta_new_cl:
        value = str(meta_new_cl).strip()
        paren_idx = value.rfind(" (")
        if paren_idx > 0:
            return value[:paren_idx].strip()
        return value
    return None
