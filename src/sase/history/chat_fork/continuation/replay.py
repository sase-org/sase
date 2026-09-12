"""Assemble continuation nodes from fork sources and render a replay."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

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
from ._assess import (
    assess_automatic_continuation_launch,
    merge_omissions,
)
from ._load import (
    delayed_starter_parent_ids,
    has_monitor_continuation_meta,
    load_agent_meta,
    monitor_payload,
    parent_node_ids,
    read_captured_node,
    read_frozen_monitor_result,
)
from ._render import prepare_legacy_payload, render_manifest
from ._source import (
    ContinuationNodeIndex,
    hydrate_missing_parents,
)
from ._util import (
    BlockContent,
    ContinuationReplayRefusal,
    ContinuationSourceError,
    block_payload_size,
    optional_ref,
    owner,
    safe_identifier,
    sha_json,
)


@dataclass(frozen=True)
class ContinuationReplayResult:
    """Rendered continuation history plus launch-eligibility assessment."""

    rendered: str
    manifest: Mapping[str, Any]
    refusals: tuple[ContinuationReplayRefusal, ...]

    def raise_for_automatic_launch(self) -> None:
        if self.refusals:
            raise self.refusals[0]


class _ReplayBuilder:
    def __init__(self) -> None:
        self.records: dict[str, ContinuationNodeWire] = {}
        self.root_ids: list[str] = []
        self.content_by_node_id: dict[str, BlockContent] = {}
        self.has_versioned_source = False
        self.seed_dirs: list[Path] = []
        self.python_omissions: list[dict[str, str | None]] = []
        self.evidence_policy: str | None = None
        self.has_historical_result = False

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
        if artifact_dir is not None:
            self.seed_dirs.append(artifact_dir)
        if historical_result:
            self.has_historical_result = True
        proc = _proc_info(source)
        if proc is not None:
            policy = fork_source_optional_string(proc, "monitor_next_output")
            if policy:
                self.evidence_policy = policy
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
            try:
                loaded = read_captured_node(artifact_dir, label=label)
            except ContinuationSourceError as exc:
                self.python_omissions.append(
                    {
                        "kind": exc.kind,
                        "node_id": None,
                        "parent_id": None,
                        "reason": str(exc),
                    }
                )
                loaded = None
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
        policy = json_string(
            meta, "monitor_next_output"
        ) or fork_source_optional_string(proc, "monitor_next_output")
        if isinstance(policy, str) and policy:
            self.evidence_policy = policy
        if frozen is not None:
            frozen_node, content = frozen
            delayed = delayed_starter_parent_ids(artifact_dir, frozen_node, meta=meta)
            if delayed:
                frozen_node = cast(
                    ContinuationNodeWire,
                    {**frozen_node, "parent_ids": delayed},
                )
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
            "evidence_policy": self.evidence_policy,
            "may_contain_raw_evidence": _legacy_may_contain_raw_evidence(source),
        }
        protected_text, has_user = _legacy_protected_text(source, artifact_dir)
        if protected_text:
            payload["protected_text"] = protected_text
            payload["has_protected_user_content"] = has_user
        payload, omission = prepare_legacy_payload(
            payload, evidence_policy=self.evidence_policy
        )
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
        payload["node_id"] = node_id
        if omission:
            omission["node_id"] = node_id
            self.python_omissions.append(omission)
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
        as_root: bool = True,
    ) -> None:
        node_id = node["node_id"]
        existing = self.records.get(node_id)
        if existing is not None and existing != node:
            raise ValueError(f"conflicting continuation node {node_id}")
        self.records[node_id] = node
        self.content_by_node_id[node_id] = content
        if as_root and node_id not in self.root_ids:
            self.root_ids.append(node_id)
        if versioned:
            self.has_versioned_source = True

    def hydrate_parents(self) -> None:
        if not self.records:
            return
        index = ContinuationNodeIndex()
        for artifact_dir in self.seed_dirs:
            index.observe_dir(artifact_dir)
            index.observe_siblings(artifact_dir)
        hydrated, omissions = hydrate_missing_parents(self.records, index)
        self.python_omissions.extend(omissions)
        for loaded in hydrated:
            self._add_node(
                loaded.node,
                loaded.content,
                versioned=True,
                as_root=False,
            )


def replay_versioned_continuation_history(
    sources: Sequence[Mapping[str, object]],
) -> ContinuationReplayResult | None:
    """Plan and render a parent-first continuation projection from exact nodes."""

    builder = _ReplayBuilder()
    for source in sources:
        builder.add_source(source)
    builder.hydrate_parents()
    if not builder.has_versioned_source or not builder.root_ids:
        return None

    prefix_reset_reason = (
        "historical evidence projection for older family monitor results"
        if builder.has_historical_result
        else None
    )

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
        "prefix_reset_reason": prefix_reset_reason,
    }
    manifest = merge_omissions(
        plan_continuation_replay(request),
        builder.python_omissions,
    )
    refusals = assess_automatic_continuation_launch(
        manifest,
        builder.content_by_node_id,
    )
    manifest = merge_omissions(
        manifest,
        [
            {
                "kind": refusal.kind,
                "node_id": None,
                "parent_id": None,
                "reason": str(refusal),
            }
            for refusal in refusals
            if refusal.kind == "failed_starter_without_checkpoint"
        ],
    )
    rendered = render_manifest(manifest, builder.content_by_node_id)
    return ContinuationReplayResult(
        rendered=rendered,
        manifest=manifest,
        refusals=refusals,
    )


def render_versioned_continuation_history(
    sources: Sequence[Mapping[str, object]],
) -> str | None:
    """Render a parent-first continuation projection when source metadata exists."""

    result = replay_versioned_continuation_history(sources)
    return None if result is None else result.rendered


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


def _legacy_may_contain_raw_evidence(source: Mapping[str, object]) -> bool:
    proc = _proc_info(source)
    if proc is None:
        return bool(source.get("kind") == "proc")
    return bool(proc.get("is_monitor") or proc.get("log_tail") or proc.get("log_path"))


def _legacy_protected_text(
    source: Mapping[str, object],
    artifact_dir: Path | None,
) -> tuple[str | None, bool]:
    path = fork_source_optional_string(source, "path")
    if path:
        try:
            text = Path(path).expanduser().read_text(encoding="utf-8")
        except OSError:
            text = None
        else:
            return text, not _legacy_may_contain_raw_evidence(source)
    proc = _proc_info(source)
    if proc is not None:
        log_tail = fork_source_optional_string(proc, "log_tail")
        if log_tail:
            return log_tail, False
    if artifact_dir is not None:
        chat = artifact_dir / "chat.md"
        try:
            text = chat.read_text(encoding="utf-8")
        except OSError:
            return None, False
        return text, True
    return None, False


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
