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
from ._refs import (
    continuation_ref_path,
    read_json_ref,
    read_text_ref,
)
from ._util import (
    BlockContent,
    ContinuationSourceError,
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


def read_captured_node(
    artifact_dir: Path,
    *,
    label: str,
    historical_result: bool = False,
) -> tuple[ContinuationNodeWire, BlockContent] | None:
    """Load the primary captured node published in *artifact_dir*."""

    meta = load_agent_meta(artifact_dir)
    node = _read_node_from_meta(artifact_dir, meta)
    if node is None:
        node = _read_monitor_node_from_meta(artifact_dir, meta)
    if node is None:
        return None
    return load_captured_node_content(
        artifact_dir,
        cast(ContinuationNodeWire, node),
        label=label,
        historical_result=historical_result,
        meta=meta,
    )


def load_captured_node_content(
    artifact_dir: Path,
    node: Mapping[str, Any],
    *,
    label: str,
    historical_result: bool = False,
    meta: Mapping[str, object] | None = None,
) -> tuple[ContinuationNodeWire, BlockContent] | None:
    """Materialize renderable content for an already-loaded continuation node."""

    kind = node.get("kind")
    if kind == "agent_delta":
        return _load_agent_delta_node(artifact_dir, node, label=label)
    if kind == "monitor_result":
        return _load_monitor_result_node(
            artifact_dir,
            node,
            label=label,
            historical_result=historical_result,
            meta=meta if meta is not None else load_agent_meta(artifact_dir),
        )
    if kind == "checkpoint":
        return _load_checkpoint_node(artifact_dir, node, label=label)
    if kind == "legacy_boundary":
        return _load_legacy_node(artifact_dir, node, label=label)
    return None


def iter_captured_nodes(
    artifact_dir: Path,
) -> list[Mapping[str, Any]]:
    """Return every continuation node record stored under *artifact_dir*."""

    nodes: dict[str, Mapping[str, Any]] = {}
    nodes_dir = artifact_dir / "continuation" / "nodes"
    if nodes_dir.is_dir():
        for path in sorted(nodes_dir.glob("*.json")):
            payload = load_json_object(path)
            node_id = payload.get("node_id") if isinstance(payload, Mapping) else None
            if isinstance(node_id, str) and node_id:
                nodes[node_id] = payload
    meta = load_agent_meta(artifact_dir)
    primary = _read_node_from_meta(artifact_dir, meta) or _read_monitor_node_from_meta(
        artifact_dir, meta
    )
    if primary is not None:
        node_id = primary.get("node_id")
        if isinstance(node_id, str) and node_id:
            nodes.setdefault(node_id, primary)
    return list(nodes.values())


def delayed_starter_parent_ids(
    artifact_dir: Path,
    node: Mapping[str, Any],
    *,
    meta: Mapping[str, object] | None = None,
) -> list[str]:
    """Return parent IDs, hydrating a settled starter when the node omitted them."""

    existing = unique_strings(node.get("parent_ids") or [])
    if existing:
        return existing
    loaded_meta = meta if meta is not None else load_agent_meta(artifact_dir)
    starter_dir = json_string(loaded_meta, "monitor_starter_artifacts_dir")
    if not starter_dir:
        return []
    starter_path = Path(starter_dir).expanduser()
    starter_meta = load_agent_meta(starter_path)
    starter_node = _read_node_from_meta(starter_path, starter_meta)
    starter_id = json_string(starter_node, "node_id") if starter_node else None
    if not starter_id:
        starter_id = json_string(starter_meta, "continuation_node_id")
    return [starter_id] if starter_id else []


def _load_agent_delta_node(
    artifact_dir: Path,
    node: Mapping[str, Any],
    *,
    label: str,
) -> tuple[ContinuationNodeWire, BlockContent] | None:
    content_ref = str(node.get("content_ref") or "")
    expected_sha = node.get("content_sha256")
    expected = expected_sha if isinstance(expected_sha, str) and expected_sha else None
    try:
        delta = read_json_ref(
            artifact_dir,
            content_ref,
            expected_sha256=expected,
        )
    except ContinuationSourceError as exc:
        delta = _read_json_ref(artifact_dir, content_ref)
        if not delta:
            raise
        if expected and sha_json(delta) != expected:
            raise ContinuationSourceError(
                "digest_mismatch",
                f"continuation content digest mismatch for {node.get('node_id')}",
            ) from exc
    payload: dict[str, Any] = dict(delta)
    payload["artifact_dir"] = str(artifact_dir)
    final_response_ref = json_string(delta, "final_response_ref")
    if final_response_ref:
        payload["final_response_text"] = _read_text_ref(
            artifact_dir, final_response_ref
        )
    payload["materialized_segments"] = _materialized_segments(artifact_dir, delta)
    checkpoint_ref = json_string(node, "checkpoint_ref") or json_string(
        delta, "handoff_checkpoint_ref"
    )
    if checkpoint_ref:
        payload["checkpoint_body"] = _read_json_ref(artifact_dir, checkpoint_ref)
        payload["checkpoint_ref"] = checkpoint_ref
    return cast(ContinuationNodeWire, dict(node)), BlockContent(
        kind="agent_delta",
        label=label,
        payload=payload,
    )


def _load_monitor_result_node(
    artifact_dir: Path,
    node: Mapping[str, Any],
    *,
    label: str,
    historical_result: bool,
    meta: Mapping[str, object],
) -> tuple[ContinuationNodeWire, BlockContent] | None:
    content_ref = str(node.get("content_ref") or "")
    expected_sha = node.get("content_sha256")
    expected = expected_sha if isinstance(expected_sha, str) and expected_sha else None
    result = _read_json_ref(artifact_dir, content_ref)
    if not result:
        return None
    if expected and sha_json(result) != expected:
        raise ContinuationSourceError(
            "digest_mismatch",
            f"monitor result digest mismatch for {node.get('node_id') or content_ref}",
        )
    hydrated = dict(node)
    delayed_parents = delayed_starter_parent_ids(artifact_dir, hydrated, meta=meta)
    if delayed_parents:
        hydrated["parent_ids"] = delayed_parents
    checkpoint_ref = json_string(hydrated, "checkpoint_ref") or json_string(
        meta, "continuation_checkpoint_ref"
    )
    payload = _monitor_payload_from_result(
        {
            "kind": "proc",
            "name": json_string(meta, "name") or label or artifact_dir.name,
            "artifact_dir": str(artifact_dir),
        },
        {
            "proc_id": json_string(meta, "monitor_id") or artifact_dir.name,
            "is_monitor": True,
            "log_tail": None,
            "log_path": None,
            "command": json_string(meta, "monitor_command"),
            "monitor_next_output": json_string(meta, "monitor_next_output"),
        },
        artifact_dir,
        meta,
        result,
        historical_result=historical_result,
    )
    payload = dict(payload)
    payload["artifact_dir"] = str(artifact_dir)
    if checkpoint_ref:
        payload["checkpoint_body"] = _read_json_ref(artifact_dir, checkpoint_ref)
        payload["checkpoint_ref"] = checkpoint_ref
    return cast(ContinuationNodeWire, hydrated), BlockContent(
        kind="monitor_result",
        label=label,
        payload=payload,
    )


def _load_checkpoint_node(
    artifact_dir: Path,
    node: Mapping[str, Any],
    *,
    label: str,
) -> tuple[ContinuationNodeWire, BlockContent] | None:
    content_ref = str(node.get("content_ref") or "")
    expected_sha = node.get("content_sha256")
    expected = expected_sha if isinstance(expected_sha, str) and expected_sha else None
    body = _read_json_ref(artifact_dir, content_ref)
    if not body:
        return None
    if expected and sha_json(body) != expected:
        raise ContinuationSourceError(
            "digest_mismatch",
            f"checkpoint digest mismatch for {node.get('node_id')}",
        )
    payload = {
        "artifact_dir": str(artifact_dir),
        "checkpoint_body": body,
        "checkpoint_ref": content_ref,
        "label": label,
    }
    return cast(ContinuationNodeWire, dict(node)), BlockContent(
        kind="checkpoint",
        label=label,
        payload=payload,
    )


def _load_legacy_node(
    artifact_dir: Path,
    node: Mapping[str, Any],
    *,
    label: str,
) -> tuple[ContinuationNodeWire, BlockContent] | None:
    content_ref = str(node.get("content_ref") or "")
    payload = dict(_read_json_ref(artifact_dir, content_ref) or {})
    payload.setdefault("label", label)
    payload["artifact_dir"] = str(artifact_dir)
    return cast(ContinuationNodeWire, dict(node)), BlockContent(
        kind="legacy_boundary",
        label=label,
        payload=payload,
    )


def _materialized_segments(
    artifact_dir: Path,
    delta: Mapping[str, Any],
) -> list[dict[str, Any]]:
    raw_segments = delta.get("materialized_local_prompt_segments")
    if not isinstance(raw_segments, list):
        return []
    segments: list[dict[str, Any]] = []
    for raw in raw_segments:
        if not isinstance(raw, Mapping):
            continue
        text_ref = raw.get("text_ref")
        provenance = raw.get("provenance")
        if not isinstance(text_ref, str) or not isinstance(provenance, str):
            continue
        expected = raw.get("text_sha256")
        try:
            text: str | None = read_text_ref(
                artifact_dir,
                text_ref,
                expected_sha256=expected if isinstance(expected, str) else None,
            )
        except ContinuationSourceError:
            text = _read_text_ref(artifact_dir, text_ref)
        if text is None:
            continue
        segment = {
            "segment_id": raw.get("segment_id"),
            "provenance": provenance,
            "source_ref": raw.get("source_ref"),
            "text": text,
            "utf8_bytes": raw.get("utf8_bytes") or len(text.encode("utf-8")),
        }
        segments.append(segment)
    return segments


def _read_monitor_node_from_meta(
    artifact_dir: Path,
    meta: Mapping[str, object],
) -> Mapping[str, Any] | None:
    node_ref = json_string(meta, "continuation_monitor_result_node_ref")
    if node_ref:
        node = _read_json_ref(artifact_dir, node_ref)
        if node:
            return node
    manifest = _read_monitor_result_manifest(artifact_dir, meta)
    node_ref = json_string(manifest, "node_ref")
    if node_ref:
        return _read_json_ref(artifact_dir, node_ref)
    return None


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
    if not ref:
        return {}
    path = continuation_ref_path(artifact_dir, ref)
    return load_json_object(path) if path is not None else {}


def _read_text_ref(artifact_dir: Path, ref: str) -> str | None:
    if not ref:
        return None
    try:
        return read_text_ref(artifact_dir, ref)
    except ContinuationSourceError:
        return None


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
