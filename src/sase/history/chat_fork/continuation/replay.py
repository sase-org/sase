"""Assemble continuation nodes from fork sources and render a replay."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.core.continuation_facade import plan_continuation_replay
from sase.core.continuation_wire import (
    CONTINUATION_WIRE_SCHEMA_VERSION,
    ContinuationNodeWire,
)

from ..common import (
    fork_source_kind,
    fork_source_optional_string,
    fork_source_string,
    json_string,
    require_proc_info,
)
from ._load import (
    has_monitor_continuation_meta,
    load_agent_meta,
    monitor_payload,
    parent_node_ids,
    read_captured_agent_node,
    read_frozen_monitor_result,
)
from ._render import render_manifest
from ._util import (
    BlockContent,
    block_payload_size,
    optional_ref,
    owner,
    safe_identifier,
    sha_json,
)


class _ReplayBuilder:
    def __init__(self) -> None:
        self.records: dict[str, ContinuationNodeWire] = {}
        self.root_ids: list[str] = []
        self.content_by_node_id: dict[str, BlockContent] = {}
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
            if has_monitor_continuation_meta(artifact_dir):
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
            loaded = read_captured_agent_node(artifact_dir, label=label)
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
        meta = load_agent_meta(artifact_dir)
        frozen = read_frozen_monitor_result(
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

        payload = monitor_payload(
            source,
            proc,
            artifact_dir,
            meta,
            historical_result=historical_result,
        )
        digest = sha_json(payload)
        proc_id = safe_identifier(
            fork_source_optional_string(proc, "proc_id") or artifact_dir.name
        )
        node_id = f"monitor-result:{proc_id}:{digest[:16]}"
        node: ContinuationNodeWire = {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "node_id": node_id,
            "kind": "monitor_result",
            "parent_ids": parent_node_ids(meta),
            "owner": owner(
                project=json_string(meta, "project_name")
                or fork_source_optional_string(proc, "project")
                or "unknown",
                run_id=artifact_dir.name,
                agent_name=fork_source_string(source, "name"),
                workspace_id=meta.get("workspace_num"),
            ),
            "content_ref": f"compat:monitor-result:{proc_id}:{digest[:16]}",
            "content_sha256": digest,
            "workspace_ref": optional_ref(
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
            BlockContent(kind="monitor_result", label=label, payload=payload),
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
        meta = load_agent_meta(artifact_dir) if artifact_dir else {}
        payload: dict[str, Any] = {
            "label": label,
            "reason": reason,
            "transcript_path": fork_source_optional_string(source, "path"),
            "artifact_dir_name": artifact_dir.name if artifact_dir else None,
        }
        digest = sha_json(payload)
        run_id = artifact_dir.name if artifact_dir else digest[:16]
        node_id = f"legacy-boundary:{safe_identifier(run_id)}:{digest[:16]}"
        node: ContinuationNodeWire = {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "node_id": node_id,
            "kind": "legacy_boundary",
            "parent_ids": parent_node_ids(meta),
            "owner": owner(
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
            BlockContent(kind="legacy_boundary", label=label, payload=payload),
            versioned=False,
        )

    def _add_node(
        self,
        node: ContinuationNodeWire,
        content: BlockContent,
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
                    block_payload_size(content)
                    for content in builder.content_by_node_id.values()
                ),
            }
        ],
    }
    manifest = plan_continuation_replay(request)
    return render_manifest(manifest, builder.content_by_node_id)


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
