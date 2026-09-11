"""Continuation-aware fork replay for exact local ancestry nodes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Literal, cast

from sase.core.continuation_facade import plan_continuation_replay
from sase.core.continuation_wire import (
    CONTINUATION_WIRE_SCHEMA_VERSION,
    ContinuationExecutionIdentityWire,
    ContinuationNodeWire,
)

from .common import (
    fork_source_kind,
    fork_source_optional_string,
    fork_source_string,
    format_text_fence,
    json_string,
    load_json_object,
    require_proc_info,
)

_BlockKind = Literal["agent_delta", "monitor_result", "legacy_boundary"]


@dataclass(frozen=True)
class _BlockContent:
    kind: _BlockKind
    label: str
    payload: Mapping[str, Any]


class _ReplayBuilder:
    def __init__(self) -> None:
        self.records: dict[str, ContinuationNodeWire] = {}
        self.root_ids: list[str] = []
        self.content_by_node_id: dict[str, _BlockContent] = {}
        self.has_versioned_source = False

    def add_source(self, source: Mapping[str, object]) -> None:
        kind = fork_source_kind(source)
        if kind == "family":
            self._add_family(source)
            return
        self._add_one(source, label=f"{kind} `{fork_source_string(source, 'name')}`")

    def _add_family(self, source: Mapping[str, object]) -> None:
        name = fork_source_string(source, "name")
        raw_members = source.get("members")
        if not isinstance(raw_members, list):
            return
        members = [member for member in raw_members if isinstance(member, Mapping)]
        members.sort(key=lambda member: _artifact_dir_name(member) or "")
        newest_monitor_index = _newest_terminal_monitor_index(members)
        for index, member in enumerate(members):
            self._add_one(
                member,
                label=f"family `{name}` member `{fork_source_string(member, 'name')}`",
                historical_result=(
                    newest_monitor_index is not None and index != newest_monitor_index
                ),
            )

    def _add_one(
        self,
        source: Mapping[str, object],
        *,
        label: str,
        historical_result: bool = False,
    ) -> None:
        artifact_dir = _artifact_dir(source)
        proc = _proc_info(source)
        if proc is not None and bool(proc.get("is_monitor")) and artifact_dir:
            if _has_monitor_continuation_meta(artifact_dir):
                self._add_monitor_result(
                    source,
                    proc,
                    artifact_dir,
                    label=label,
                    historical_result=historical_result,
                )
            else:
                self._add_legacy_boundary(
                    source,
                    artifact_dir,
                    label=label,
                    reason="monitor source lacks continuation parent or intent metadata",
                )
            return

        if artifact_dir:
            loaded = _read_captured_agent_node(artifact_dir, label=label)
            if loaded is not None:
                node, content = loaded
                self._add_node(node, content, versioned=True)
                return

        path = fork_source_optional_string(source, "path")
        if path:
            self._add_legacy_boundary(
                source,
                artifact_dir,
                label=label,
                reason="source lacks a recoverable continuation node",
            )

    def _add_monitor_result(
        self,
        source: Mapping[str, object],
        proc: Mapping[str, object],
        artifact_dir: Path,
        *,
        label: str,
        historical_result: bool = False,
    ) -> None:
        meta = load_json_object(artifact_dir / "agent_meta.json")
        frozen = _read_frozen_monitor_result(
            source,
            proc,
            artifact_dir,
            meta,
            label=label,
            historical_result=historical_result,
        )
        if frozen is not None:
            frozen_node, content = frozen
            self._add_node(frozen_node, content, versioned=True)
            return

        payload = _monitor_payload(
            source,
            proc,
            artifact_dir,
            meta,
            historical_result=historical_result,
        )
        digest = _sha_json(payload)
        proc_id = _safe_identifier(
            fork_source_optional_string(proc, "proc_id") or artifact_dir.name
        )
        node_id = f"monitor-result:{proc_id}:{digest[:16]}"
        node: ContinuationNodeWire = {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "node_id": node_id,
            "kind": "monitor_result",
            "parent_ids": _parent_node_ids(meta),
            "owner": _owner(
                project=json_string(meta, "project_name")
                or fork_source_optional_string(proc, "project")
                or "unknown",
                run_id=artifact_dir.name,
                agent_name=fork_source_string(source, "name"),
                workspace_id=meta.get("workspace_num"),
            ),
            "content_ref": f"compat:monitor-result:{proc_id}:{digest[:16]}",
            "content_sha256": digest,
            "workspace_ref": _optional_ref(
                json_string(meta, "continuation_workspace_ref")
                or json_string(meta, "workspace_dir")
            ),
        }
        checkpoint_ref = json_string(meta, "continuation_checkpoint_ref")
        if checkpoint_ref:
            node["checkpoint_ref"] = checkpoint_ref
        intent_ref = json_string(meta, "continuation_intent_ref")
        if intent_ref:
            node["intent_ref"] = intent_ref
        self._add_node(
            node,
            _BlockContent(kind="monitor_result", label=label, payload=payload),
            versioned=True,
        )

    def _add_legacy_boundary(
        self,
        source: Mapping[str, object],
        artifact_dir: Path | None,
        *,
        label: str,
        reason: str,
    ) -> None:
        meta = (
            load_json_object(artifact_dir / "agent_meta.json") if artifact_dir else {}
        )
        payload: dict[str, Any] = {
            "label": label,
            "reason": reason,
            "transcript_path": fork_source_optional_string(source, "path"),
            "artifact_dir_name": artifact_dir.name if artifact_dir else None,
        }
        digest = _sha_json(payload)
        run_id = artifact_dir.name if artifact_dir else digest[:16]
        node_id = f"legacy-boundary:{_safe_identifier(run_id)}:{digest[:16]}"
        node: ContinuationNodeWire = {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "node_id": node_id,
            "kind": "legacy_boundary",
            "parent_ids": _parent_node_ids(meta),
            "owner": _owner(
                project=json_string(meta, "project_name") or "unknown",
                run_id=run_id,
                agent_name=fork_source_string(source, "name"),
                workspace_id=meta.get("workspace_num"),
            ),
            "content_ref": f"compat:legacy-boundary:{digest[:16]}",
            "content_sha256": digest,
        }
        self._add_node(
            node,
            _BlockContent(kind="legacy_boundary", label=label, payload=payload),
            versioned=False,
        )

    def _add_node(
        self,
        node: ContinuationNodeWire,
        content: _BlockContent,
        *,
        versioned: bool,
    ) -> None:
        node_id = node["node_id"]
        existing = self.records.get(node_id)
        if existing is not None and existing != node:
            raise ValueError(f"conflicting continuation node {node_id}")
        self.records[node_id] = node
        self.content_by_node_id[node_id] = content
        if node_id not in self.root_ids:
            self.root_ids.append(node_id)
        if versioned:
            self.has_versioned_source = True


def render_versioned_continuation_history(
    sources: Sequence[Mapping[str, object]],
) -> str | None:
    """Render a parent-first continuation projection when source metadata exists."""

    builder = _ReplayBuilder()
    for source in sources:
        builder.add_source(source)
    if not builder.has_versioned_source or not builder.root_ids:
        return None

    request = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "records": list(builder.records.values()),
        "root_ids": builder.root_ids,
        "rendered_components": [
            {
                "name": "continuation_replay_sources",
                "utf8_bytes": sum(
                    _block_payload_size(content)
                    for content in builder.content_by_node_id.values()
                ),
            }
        ],
    }
    manifest = plan_continuation_replay(request)
    return _render_manifest(manifest, builder.content_by_node_id)


def _render_manifest(
    manifest: Mapping[str, Any],
    content_by_node_id: Mapping[str, _BlockContent],
) -> str:
    blocks = [
        block
        for block in manifest.get("stable_blocks", [])
        if isinstance(block, Mapping)
    ]
    if not blocks:
        return ""
    lines = [
        "This fork uses versioned continuation replay. Blocks are stable, "
        "parent-first projections of exact continuation nodes; any historical "
        "source without recoverable node provenance is represented as an opaque "
        "legacy boundary.",
        "",
        f"- **Projection version:** `{manifest.get('projection_version', 'unknown')}`",
        f"- **Ordered nodes:** `{len(blocks)}`",
    ]
    omissions = [
        omission
        for omission in manifest.get("omissions", [])
        if isinstance(omission, Mapping)
    ]
    if omissions:
        lines.append("- **Omissions:**")
        lines.extend(f"  - {_format_omission(omission)}" for omission in omissions)

    for block in blocks:
        node_id = str(block.get("node_id") or "")
        content = content_by_node_id.get(node_id)
        lines.extend(["", *_render_block(block, content)])
    return "\n".join(lines).rstrip()


def _render_block(
    block: Mapping[str, Any],
    content: _BlockContent | None,
) -> list[str]:
    block_id = str(block.get("block_id") or "unknown")
    node_id = str(block.get("node_id") or "unknown")
    kind = str(block.get("kind") or "unknown")
    parents = block.get("parent_ids")
    parent_text = ", ".join(f"`{item}`" for item in parents) if parents else "(none)"
    rows = [
        f"## Continuation Block `{block_id}`",
        "",
        f"- **Node:** `{node_id}`",
        f"- **Kind:** `{kind}`",
        f"- **Parents:** {parent_text}",
        f"- **Content:** `{block.get('content_ref') or 'unknown'}`",
    ]
    checkpoint_ref = block.get("checkpoint_ref")
    if isinstance(checkpoint_ref, str) and checkpoint_ref:
        rows.append(f"- **Checkpoint:** `{checkpoint_ref}`")
    intent_ref = block.get("intent_ref")
    if isinstance(intent_ref, str) and intent_ref:
        rows.append(f"- **Intent:** `{intent_ref}`")

    if content is None:
        rows.extend(
            [
                "",
                "### Missing Projection",
                "",
                "The continuation node was ordered by Rust, but no local "
                "projection content was available in this source set.",
            ]
        )
        return rows
    if content.kind == "agent_delta":
        rows.extend(["", *_render_agent_delta(content.payload)])
    elif content.kind == "monitor_result":
        rows.extend(["", *_render_monitor_result(content.payload)])
    else:
        rows.extend(["", *_render_legacy_boundary(content.payload)])
    return rows


def _render_agent_delta(payload: Mapping[str, Any]) -> list[str]:
    lines = [
        "### User",
        "",
        str(payload.get("authored_local_request") or "").strip(),
        "",
        "### Assistant",
        "",
    ]
    final_response = payload.get("final_response_text")
    if isinstance(final_response, str) and final_response:
        lines.append(final_response.strip())
    else:
        status = str(payload.get("status") or "unknown")
        lines.append(f"_No final response was captured for local status `{status}`._")
    return lines


def _render_monitor_result(payload: Mapping[str, Any]) -> list[str]:
    result = payload.get("result")
    selection = payload.get("selection")
    if isinstance(result, Mapping) and isinstance(selection, Mapping):
        from sase.monitor.result_projection import render_monitor_result_block

        return render_monitor_result_block(
            result,
            selection,
            output_text=(
                payload.get("output_text")
                if isinstance(payload.get("output_text"), str)
                else None
            ),
            output_log_path=(
                payload.get("output_log_path")
                if isinstance(payload.get("output_log_path"), str)
                else None
            ),
            command_text=(
                payload.get("command_text")
                if isinstance(payload.get("command_text"), str)
                else None
            ),
            heading_level=3,
        )

    lines = [
        "### Monitor Result",
        "",
        f"- **Monitor ID:** `{payload.get('monitor_id') or 'unknown'}`",
        f"- **Outcome:** `{payload.get('status') or 'unknown'}`",
    ]
    exit_code = payload.get("exit_code")
    if isinstance(exit_code, int):
        lines.append(f"- **Exit code:** `{exit_code}`")
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd:
        lines.append(f"- **Cwd:** `{cwd}`")
    started_at = payload.get("started_at")
    if isinstance(started_at, str) and started_at:
        lines.append(f"- **Started:** `{started_at}`")
    finished_at = payload.get("finished_at")
    if isinstance(finished_at, str) and finished_at:
        lines.append(f"- **Finished:** `{finished_at}`")
    log_path = payload.get("log_path")
    proc_id = payload.get("monitor_id")
    if isinstance(log_path, str) and log_path:
        pointer = f"- **Retained output:** inspect `{log_path}`"
        if isinstance(proc_id, str) and proc_id:
            pointer += f" or run `sase monitor show {proc_id} --all-lines`"
        lines.append(pointer)
    command = payload.get("command")
    if isinstance(command, str) and command:
        lines.extend(["", "#### Command", "", format_text_fence(command)])
    return lines


def _render_legacy_boundary(payload: Mapping[str, Any]) -> list[str]:
    lines = [
        "### Opaque Legacy Boundary",
        "",
        "This source lacks recoverable continuation node provenance, so replay "
        "does not guess transcript turns from Markdown headings.",
        "",
        f"- **Source:** {payload.get('label') or 'unknown'}",
        f"- **Reason:** {payload.get('reason') or 'unknown'}",
    ]
    transcript = payload.get("transcript_path")
    if isinstance(transcript, str) and transcript:
        lines.append(f"- **Transcript:** `{transcript}`")
    return lines


def _read_frozen_monitor_result(
    source: Mapping[str, object],
    proc: Mapping[str, object],
    artifact_dir: Path,
    meta: Mapping[str, object],
    *,
    label: str,
    historical_result: bool,
) -> tuple[ContinuationNodeWire, _BlockContent] | None:
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
        and _sha_json(result) != expected_sha
    ):
        raise ValueError(
            f"monitor result digest mismatch for {node.get('node_id') or node_ref}"
        )
    return cast(ContinuationNodeWire, node), _BlockContent(
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
    return {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "kind": "monitor_result",
        "source_name": fork_source_string(source, "name"),
        "artifact_dir_name": artifact_dir.name,
        "result": result,
        "selection": selection,
        "output_text": fork_source_optional_string(proc, "log_tail"),
        "output_log_path": fork_source_optional_string(proc, "log_path"),
        "command_text": fork_source_optional_string(proc, "command"),
        "historical_result": historical_result,
        "next_action_ref": json_string(meta, "continuation_intent_ref"),
        "checkpoint_ref": json_string(meta, "continuation_checkpoint_ref"),
    }


def _read_captured_agent_node(
    artifact_dir: Path,
    *,
    label: str,
) -> tuple[ContinuationNodeWire, _BlockContent] | None:
    meta = load_json_object(artifact_dir / "agent_meta.json")
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
        and _sha_json(delta) != expected_sha
    ):
        raise ValueError(f"continuation content digest mismatch for {node['node_id']}")
    payload: dict[str, Any] = dict(delta)
    final_response_ref = json_string(delta, "final_response_ref")
    if final_response_ref:
        payload["final_response_text"] = _read_text_ref(
            artifact_dir, final_response_ref
        )
    return cast(ContinuationNodeWire, node), _BlockContent(
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


def _monitor_payload(
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

    log_tail = fork_source_optional_string(proc, "log_tail")
    result = build_monitor_result_wire(
        monitor_id=fork_source_optional_string(proc, "proc_id") or artifact_dir.name,
        monitor_state=fork_source_optional_string(proc, "status") or "unknown",
        exit_code=_int_or_none(proc.get("exit_code")),
        command=fork_source_optional_string(proc, "command"),
        cwd=fork_source_optional_string(proc, "cwd") or "unknown",
        started_at=fork_source_optional_string(proc, "started_at") or "unknown",
        stopped_at=fork_source_optional_string(proc, "finished_at")
        or json_string(meta, "stopped_at"),
        elapsed_seconds=_number_or_none(proc.get("elapsed_seconds")),
        timeout_seconds=_number_or_none(proc.get("timeout_seconds")),
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
    return {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "kind": "monitor_result_compat",
        "source_name": fork_source_string(source, "name"),
        "artifact_dir_name": artifact_dir.name,
        "result": result,
        "selection": selection,
        "output_text": log_tail,
        "output_log_path": fork_source_optional_string(proc, "log_path"),
        "command_text": fork_source_optional_string(proc, "command"),
        "historical_result": historical_result,
        "next_action_ref": json_string(meta, "continuation_intent_ref"),
        "checkpoint_ref": json_string(meta, "continuation_checkpoint_ref"),
    }


def _proc_info(source: Mapping[str, object]) -> Mapping[str, object] | None:
    try:
        return require_proc_info(source, fork_source_string(source, "name"))
    except ValueError:
        return None


def _artifact_dir(source: Mapping[str, object]) -> Path | None:
    value = fork_source_optional_string(source, "artifact_dir")
    if not value:
        return None
    return Path(value).expanduser()


def _artifact_dir_name(source: Mapping[str, object]) -> str | None:
    artifact_dir = _artifact_dir(source)
    return artifact_dir.name if artifact_dir is not None else None


def _newest_terminal_monitor_index(
    members: Sequence[Mapping[str, object]],
) -> int | None:
    for index in range(len(members) - 1, -1, -1):
        proc = _proc_info(members[index])
        if (
            proc is not None
            and bool(proc.get("is_monitor"))
            and bool(proc.get("terminal"))
            and _artifact_dir(members[index]) is not None
        ):
            return index
    return None


def _has_monitor_continuation_meta(artifact_dir: Path) -> bool:
    meta = load_json_object(artifact_dir / "agent_meta.json")
    return bool(
        json_string(meta, "continuation_monitor_result_ref")
        or json_string(meta, "continuation_monitor_result_node_ref")
        or json_string(meta, "continuation_monitor_result_manifest_ref")
        or json_string(meta, "continuation_intent_ref")
        or json_string(meta, "continuation_checkpoint_ref")
        or _parent_node_ids(meta)
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


def _parent_node_ids(meta: Mapping[str, object]) -> list[str]:
    return _unique_strings(
        [
            meta.get("continuation_parent_node_id"),
            *_iter_string_list(meta.get("continuation_parent_node_ids")),
            meta.get("continuation_parent"),
        ]
    )


def _owner(
    *,
    project: str,
    run_id: str,
    agent_name: str,
    workspace_id: object,
) -> ContinuationExecutionIdentityWire:
    owner: ContinuationExecutionIdentityWire = {
        "project": _safe_identifier(project),
        "run_id": _safe_identifier(run_id),
        "agent_name": _safe_identifier(agent_name),
    }
    if workspace_id is not None:
        owner["workspace_id"] = _safe_identifier(workspace_id)
    return owner


def _optional_ref(value: str | None) -> str | None:
    if value is None:
        return None
    if not value or any(ch.isspace() for ch in value):
        return f"ref:{_sha_text(value)[:16]}"
    return value


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _number_or_none(value: object) -> int | float | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, (int, float)) else None


def _format_omission(omission: Mapping[str, Any]) -> str:
    kind = str(omission.get("kind") or "unknown")
    reason = str(omission.get("reason") or "unknown")
    node_id = omission.get("node_id")
    parent_id = omission.get("parent_id")
    details = []
    if isinstance(node_id, str) and node_id:
        details.append(f"node `{node_id}`")
    if isinstance(parent_id, str) and parent_id:
        details.append(f"parent `{parent_id}`")
    suffix = " · " + ", ".join(details) if details else ""
    return f"`{kind}`: {reason}{suffix}"


def _block_payload_size(content: _BlockContent) -> int:
    return len(_json_bytes(content.payload))


def _sha_json(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_json_bytes(payload)).hexdigest()


def _sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(_json_safe(payload), indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray | str):
        return [_json_safe(item) for item in value]
    return str(value)


def _safe_identifier(value: object, *, max_len: int = 80) -> str:
    text = str(value).strip() or "unknown"
    safe = "".join(ch if ch.isalnum() or ch in "_.:-" else "_" for ch in text)
    safe = safe.strip("_.:-") or "unknown"
    if len(safe.encode("utf-8")) <= max_len:
        return safe
    digest = _sha_text(safe)[:16]
    keep = max(1, max_len - len(digest) - 1)
    return f"{safe[:keep]}:{digest}"


def _unique_strings(values: Sequence[object]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _iter_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


__all__ = ["render_versioned_continuation_history"]
