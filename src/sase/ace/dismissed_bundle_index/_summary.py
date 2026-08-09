"""Projection between dismissed bundle JSON, SQLite rows, and summaries."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

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
    return DismissedBundleSummary(
        raw_suffix=raw_suffix,
        bundle_path=str(path),
        shard=shard,
        filename=filename,
        agent_type=string_or_default(bundle.get("agent_type"), "run"),
        cl_name=string_or_default(bundle.get("cl_name"), "unknown"),
        agent_name=optional_str(bundle.get("agent_name")),
        status=string_or_default(bundle.get("status"), "DONE"),
        start_time=optional_str(bundle.get("start_time")),
        stop_time=optional_str(bundle.get("stop_time")),
        project_file=project_file,
        model=optional_str(bundle.get("model")),
        llm_provider=llm_provider,
        vcs_provider=optional_str(bundle.get("vcs_provider")),
        workflow=optional_str(bundle.get("workflow")),
        is_workflow_child=_is_workflow_child(bundle),
        parent_timestamp=optional_str(bundle.get("parent_timestamp")),
        step_index=optional_int(bundle.get("step_index")),
        step_name=optional_str(bundle.get("step_name")),
        retry_of_timestamp=optional_str(bundle.get("retry_of_timestamp")),
        retried_as_timestamp=optional_str(bundle.get("retried_as_timestamp")),
        retry_chain_root_timestamp=optional_str(
            bundle.get("retry_chain_root_timestamp")
        ),
        retry_attempt=optional_int(bundle.get("retry_attempt")) or 0,
        meta_changespec=_meta_patch(bundle),  # legacy compatibility alias
    )


def summary_from_row(row: sqlite3.Row) -> DismissedBundleSummary:
    return DismissedBundleSummary(
        raw_suffix=str(row["raw_suffix"]),
        bundle_path=str(row["bundle_path"]),
        shard=str(row["shard"]),
        filename=str(row["filename"]),
        agent_type=str(row["agent_type"]),
        cl_name=str(row["cl_name"]),
        agent_name=optional_str(row["agent_name"]),
        status=str(row["status"]),
        start_time=optional_str(row["start_time"]),
        stop_time=optional_str(row["stop_time"]),
        project_file=optional_str(row["project_file"]),
        model=optional_str(row["model"]),
        llm_provider=optional_str(row["llm_provider"]),
        vcs_provider=optional_str(row["vcs_provider"]),
        workflow=optional_str(row["workflow"]),
        is_workflow_child=bool(row["is_workflow_child"]),
        parent_timestamp=optional_str(row["parent_timestamp"]),
        step_index=optional_int(row["step_index"]),
        step_name=optional_str(row["step_name"]),
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
