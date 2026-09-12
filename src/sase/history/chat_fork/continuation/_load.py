"""Load captured continuation nodes and build replay block payloads."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from sase.core.continuation_wire import (
    CONTINUATION_WIRE_SCHEMA_VERSION,
    ContinuationNodeWire,
)

from ..common import (
    fork_source_optional_string,
    fork_source_string,
    json_string,
    load_json_object,
)
from ._util import (
    BlockContent,
    int_or_none,
    iter_string_list,
    number_or_none,
    sha_json,
    unique_strings,
)


def load_agent_meta(artifact_dir: Path) -> Mapping[str, object]:
    return load_json_object(artifact_dir / "agent_meta.json")


def read_frozen_monitor_result(
    source: Mapping[str, object],
    proc: Mapping[str, object],
    artifact_dir: Path,
    meta: Mapping[str, object],
    *,
    label: str,
    historical_result: bool,
) -> tuple[ContinuationNodeWire, BlockContent] | None:
    manifest = _read_monitor_result_manifest(artifact_dir, meta)
    node_ref = json_string(meta, "continuation_monitor_result_node_ref") or json_string(
        manifest,
        "node_ref",
    )
    if not node_ref:
        return None
    node = _read_json_ref(artifact_dir, node_ref)
    if not node or node.get("kind") != "monitor_result":
        return None
    result_ref = (
        json_string(meta, "continuation_monitor_result_ref")
        or json_string(manifest, "result_ref")
        or json_string(node, "content_ref")
    )
    if not result_ref:
        return None
    result = _read_json_ref(artifact_dir, result_ref)
    if not result:
        return None
    expected_sha = node.get("content_sha256")
    if (
        isinstance(expected_sha, str)
        and expected_sha
        and sha_json(result) != expected_sha
    ):
        raise ValueError(
            f"monitor result digest mismatch for {node.get('node_id') or node_ref}"
        )
    return cast(ContinuationNodeWire, node), BlockContent(
        kind="monitor_result",
        label=label,
        payload=_monitor_payload_from_result(
            source,
            proc,
            artifact_dir,
            meta,
            result,
            historical_result=historical_result,
        ),
    )


def _monitor_payload_from_result(
    source: Mapping[str, object],
    proc: Mapping[str, object],
    artifact_dir: Path,
    meta: Mapping[str, object],
    result: Mapping[str, Any],
    *,
    historical_result: bool,
) -> Mapping[str, Any]:
    from sase.monitor.result_projection import (
        LEGACY_NEXT_OUTPUT,
        select_monitor_result_evidence,
    )
    from sase.monitor.diagnostics import read_selected_diagnostics_text

    diagnostic_manifest = _diagnostic_manifest_payload(artifact_dir, meta)
    selection = select_monitor_result_evidence(
        result,
        next_output=(
            json_string(meta, "monitor_next_output")
            or fork_source_optional_string(proc, "monitor_next_output")
            or LEGACY_NEXT_OUTPUT
        ),
        diagnostic_manifest=diagnostic_manifest,
        historical_result=historical_result,
    )
    selected_diagnostics = read_selected_diagnostics_text(
        artifact_dir,
        selection=selection,
        manifest=dict(diagnostic_manifest),
    )
    return {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "kind": "monitor_result",
        "source_name": fork_source_string(source, "name"),
        "artifact_dir_name": artifact_dir.name,
        "result": result,
        "selection": selection,
        "selected_diagnostics_text": selected_diagnostics.text,
        "output_text": fork_source_optional_string(proc, "log_tail"),
        "output_log_path": fork_source_optional_string(proc, "log_path"),
        "command_text": fork_source_optional_string(proc, "command"),
        "historical_result": historical_result,
        "next_action_ref": json_string(meta, "continuation_intent_ref"),
        "checkpoint_ref": json_string(meta, "continuation_checkpoint_ref"),
    }


def read_captured_agent_node(
    artifact_dir: Path,
    *,
    label: str,
) -> tuple[ContinuationNodeWire, BlockContent] | None:
    meta = load_agent_meta(artifact_dir)
    node = _read_node_from_meta(artifact_dir, meta)
    if node is None:
        return None
    if node.get("kind") != "agent_delta":
        return None
    delta = _read_json_ref(artifact_dir, str(node.get("content_ref") or ""))
    if not delta:
        return None
    expected_sha = node.get("content_sha256")
    if (
        isinstance(expected_sha, str)
        and expected_sha
        and sha_json(delta) != expected_sha
    ):
        raise ValueError(f"continuation content digest mismatch for {node['node_id']}")
    payload: dict[str, Any] = dict(delta)
    final_response_ref = json_string(delta, "final_response_ref")
    if final_response_ref:
        payload["final_response_text"] = _read_text_ref(
            artifact_dir, final_response_ref
        )
    return cast(ContinuationNodeWire, node), BlockContent(
        kind="agent_delta",
        label=label,
        payload=payload,
    )


def _read_node_from_meta(
    artifact_dir: Path,
    meta: Mapping[str, object],
) -> Mapping[str, Any] | None:
    node_ref = json_string(meta, "continuation_node_ref")
    if node_ref:
        node = _read_json_ref(artifact_dir, node_ref)
        if node:
            return node

    manifest = _read_continuation_manifest(artifact_dir, meta)
    node_ref = json_string(manifest, "node_ref")
    if node_ref:
        return _read_json_ref(artifact_dir, node_ref)
    return None


def _read_continuation_manifest(
    artifact_dir: Path,
    meta: Mapping[str, object],
) -> Mapping[str, Any]:
    manifest_path = json_string(meta, "continuation_manifest_path")
    if manifest_path:
        payload = load_json_object(Path(manifest_path))
        if payload:
            return payload
    return load_json_object(artifact_dir / "continuation" / "manifest.json")


def _read_json_ref(artifact_dir: Path, ref: str) -> Mapping[str, Any]:
    path = _local_continuation_ref_path(artifact_dir, ref)
    return load_json_object(path) if path is not None else {}


def _read_text_ref(artifact_dir: Path, ref: str) -> str | None:
    path = _local_continuation_ref_path(artifact_dir, ref)
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _local_continuation_ref_path(artifact_dir: Path, ref: str) -> Path | None:
    prefix = "local:continuation/"
    if not ref.startswith(prefix):
        return None
    root = (artifact_dir / "continuation").resolve(strict=False)
    path = (root / ref.removeprefix(prefix)).resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path


def monitor_payload(
    source: Mapping[str, object],
    proc: Mapping[str, object],
    artifact_dir: Path,
    meta: Mapping[str, object],
    *,
    historical_result: bool,
) -> Mapping[str, Any]:
    from sase.monitor.result_projection import (
        LEGACY_NEXT_OUTPUT,
        build_monitor_result_wire,
        select_monitor_result_evidence,
    )
    from sase.monitor.diagnostics import read_selected_diagnostics_text

    log_tail = fork_source_optional_string(proc, "log_tail")
    result = build_monitor_result_wire(
        monitor_id=fork_source_optional_string(proc, "proc_id") or artifact_dir.name,
        monitor_state=fork_source_optional_string(proc, "status") or "unknown",
        exit_code=int_or_none(proc.get("exit_code")),
        command=fork_source_optional_string(proc, "command"),
        cwd=fork_source_optional_string(proc, "cwd") or "unknown",
        started_at=fork_source_optional_string(proc, "started_at") or "unknown",
        stopped_at=fork_source_optional_string(proc, "finished_at")
        or json_string(meta, "stopped_at"),
        elapsed_seconds=number_or_none(proc.get("elapsed_seconds")),
        timeout_seconds=number_or_none(proc.get("timeout_seconds")),
        timeout_kind=proc.get("monitor_timeout_kind")
        or meta.get("monitor_timeout_kind"),
        starter_execution_id=(
            json_string(meta, "monitor_starter_agent")
            or json_string(meta, "parent_timestamp")
            or fork_source_string(source, "name")
        ),
        workspace_identity=(
            json_string(meta, "continuation_workspace_ref")
            or json_string(meta, "workspace_dir")
            or fork_source_optional_string(proc, "cwd")
        ),
        diagnostic_manifest_ref=json_string(meta, "monitor_diagnostic_manifest_ref"),
        retained_log={
            "log_ref": json_string(meta, "monitor_retained_log_ref"),
            "local_locator": fork_source_optional_string(proc, "log_path"),
            "total_observed_bytes": len(log_tail.encode("utf-8")) if log_tail else 0,
            "complete": not bool(proc.get("log_truncated")),
            "drain_confirmed": True,
        },
        result_seed_extra={
            "artifact_dir_name": artifact_dir.name,
            "compat": True,
        },
    )
    diagnostic_manifest = _diagnostic_manifest_payload(artifact_dir, meta)
    selection = select_monitor_result_evidence(
        result,
        next_output=(
            json_string(meta, "monitor_next_output")
            or fork_source_optional_string(proc, "monitor_next_output")
            or LEGACY_NEXT_OUTPUT
        ),
        diagnostic_manifest=diagnostic_manifest,
        historical_result=historical_result,
    )
    selected_diagnostics = read_selected_diagnostics_text(
        artifact_dir,
        selection=selection,
        manifest=dict(diagnostic_manifest),
    )
    return {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "kind": "monitor_result_compat",
        "source_name": fork_source_string(source, "name"),
        "artifact_dir_name": artifact_dir.name,
        "result": result,
        "selection": selection,
        "selected_diagnostics_text": selected_diagnostics.text,
        "output_text": log_tail,
        "output_log_path": fork_source_optional_string(proc, "log_path"),
        "command_text": fork_source_optional_string(proc, "command"),
        "historical_result": historical_result,
        "next_action_ref": json_string(meta, "continuation_intent_ref"),
        "checkpoint_ref": json_string(meta, "continuation_checkpoint_ref"),
    }


def has_monitor_continuation_meta(artifact_dir: Path) -> bool:
    meta = load_agent_meta(artifact_dir)
    return bool(
        json_string(meta, "continuation_monitor_result_ref")
        or json_string(meta, "continuation_monitor_result_node_ref")
        or json_string(meta, "continuation_monitor_result_manifest_ref")
        or json_string(meta, "continuation_intent_ref")
        or json_string(meta, "continuation_checkpoint_ref")
        or parent_node_ids(meta)
    )


def _diagnostic_manifest_payload(
    artifact_dir: Path,
    meta: Mapping[str, object],
) -> Mapping[str, Any]:
    manifest_path = json_string(meta, "monitor_diagnostic_manifest_path")
    if manifest_path:
        payload = load_json_object(Path(manifest_path))
        if payload:
            return cast(Mapping[str, Any], payload)
    return cast(
        Mapping[str, Any],
        load_json_object(artifact_dir / "diagnostics" / "diagnostic_manifest.json"),
    )


def _read_monitor_result_manifest(
    artifact_dir: Path,
    meta: Mapping[str, object],
) -> Mapping[str, object]:
    manifest_path = json_string(meta, "continuation_monitor_result_manifest_path")
    if manifest_path:
        payload = load_json_object(Path(manifest_path))
        if payload:
            return payload
    return load_json_object(
        artifact_dir / "continuation" / "monitor_result_manifest.json"
    )


def parent_node_ids(meta: Mapping[str, object]) -> list[str]:
    return unique_strings(
        [
            meta.get("continuation_parent_node_id"),
            *iter_string_list(meta.get("continuation_parent_node_ids")),
            meta.get("continuation_parent"),
        ]
    )
