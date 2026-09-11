"""Result models for continuation capture persistence."""

from __future__ import annotations

from dataclasses import dataclass

from sase.core.continuation_wire import ContinuationPromptSegmentProvenance


@dataclass(frozen=True)
class ContinuationSegmentCapture:
    """Captured material that contributed to a local prompt."""

    text: str
    provenance: ContinuationPromptSegmentProvenance
    source_ref: str | None = None
    source_label: str | None = None


@dataclass(frozen=True)
class PreparedPromptCaptureResult:
    """Pointer to the last prepared prompt capture in an artifacts dir."""

    prepared_ref: str
    prepared_path: str
    materialized_prompt_ref: str
    materialized_prompt_sha256: str
    materialized_prompt_bytes: int
    segment_count: int


@dataclass(frozen=True)
class ContinuationPublishResult:
    """Pointers published for an agent-delta continuation node."""

    node_id: str
    manifest_ref: str
    manifest_path: str
    node_ref: str
    agent_delta_ref: str
    workspace_ref: str | None

    def marker_projection(self) -> dict[str, str]:
        """Return the compact continuation object stored on done markers."""

        projection = {
            "node_id": self.node_id,
            "manifest_ref": self.manifest_ref,
            "node_ref": self.node_ref,
            "agent_delta_ref": self.agent_delta_ref,
        }
        if self.workspace_ref:
            projection["workspace_ref"] = self.workspace_ref
        return projection


@dataclass(frozen=True)
class MonitorResultPublishResult:
    """Pointers published for a frozen monitor-result continuation node."""

    result_id: str
    node_id: str
    manifest_ref: str
    manifest_path: str
    result_ref: str
    result_path: str
    result_sha256: str
    node_ref: str

    def marker_projection(self) -> dict[str, str]:
        """Return the compact continuation object stored on monitor markers."""

        return {
            "continuation_monitor_result_id": self.result_id,
            "continuation_monitor_result_ref": self.result_ref,
            "continuation_monitor_result_path": self.result_path,
            "continuation_monitor_result_sha256": self.result_sha256,
            "continuation_monitor_result_node_id": self.node_id,
            "continuation_monitor_result_node_ref": self.node_ref,
            "continuation_monitor_result_manifest_ref": self.manifest_ref,
            "continuation_monitor_result_manifest_path": self.manifest_path,
            "continuation_node_id": self.node_id,
            "continuation_node_ref": self.node_ref,
            "continuation_manifest_ref": self.manifest_ref,
            "continuation_manifest_path": self.manifest_path,
        }


__all__ = [
    "ContinuationPublishResult",
    "ContinuationSegmentCapture",
    "MonitorResultPublishResult",
    "PreparedPromptCaptureResult",
]
