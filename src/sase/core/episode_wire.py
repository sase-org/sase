"""Wire records for deterministic episodic-memory episodes.

These dataclasses mirror ``sase_core::episode`` and define the stable
Python/Rust boundary for Phase 1 of the structured episode MVP.
"""

from __future__ import annotations

from dataclasses import dataclass, field

EPISODE_WIRE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class EpisodeSourceRefWire:
    id: str
    kind: str
    path: str
    label: str | None = None
    exists: bool = False
    size_bytes: int | None = None
    sha256: str | None = None


@dataclass(frozen=True)
class EpisodeNodeWire:
    id: str
    kind: str
    label: str | None = None
    source_id: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EpisodeEdgeWire:
    id: str
    from_node_id: str
    to_node_id: str
    kind: str
    evidence_ids: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EpisodeEventWire:
    id: str
    kind: str
    title: str
    timestamp: str | None = None
    description: str | None = None
    evidence_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EpisodeLessonWire:
    id: str
    kind: str
    text: str
    evidence_ids: list[str] = field(default_factory=list)
    source_confidence: str = "deterministic"


@dataclass(frozen=True)
class EpisodeWire:
    schema_version: int
    episode_id: str
    project: str
    title: str
    summary: str
    root_source_id: str
    sources: list[EpisodeSourceRefWire] = field(default_factory=list)
    nodes: list[EpisodeNodeWire] = field(default_factory=list)
    edges: list[EpisodeEdgeWire] = field(default_factory=list)
    events: list[EpisodeEventWire] = field(default_factory=list)
    lessons: list[EpisodeLessonWire] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EpisodeBuildRequestWire:
    schema_version: int
    project: str
    selector_kind: str | None = None
    selector_value: str | None = None
    since: str | None = None
    until: str | None = None
    limit: int | None = None
    dry_run: bool = False
    force: bool = False
    source_refs: list[EpisodeSourceRefWire] = field(default_factory=list)


@dataclass(frozen=True)
class EpisodeBuildReportWire:
    schema_version: int
    project: str
    source_count: int
    lesson_count: int
    episode_id: str | None = None
    would_write: bool = False
    changed: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EpisodeStorageIndexRowWire:
    schema_version: int
    episode_id: str
    project: str
    title: str
    source_count: int
    lesson_path: str
    content_sha256: str
    root_agent_names: list[str] = field(default_factory=list)
    changespec_name: str | None = None
    bead_ids: list[str] = field(default_factory=list)
    outcome: str | None = None
    first_event_at: str | None = None
    last_event_at: str | None = None


@dataclass(frozen=True)
class EpisodeSourceVerifyResultWire:
    source_id: str
    path: str
    expected_exists: bool
    actual_exists: bool
    status: str
    expected_size_bytes: int | None = None
    actual_size_bytes: int | None = None
    expected_sha256: str | None = None
    actual_sha256: str | None = None


@dataclass(frozen=True)
class EpisodeVerifyReportWire:
    schema_version: int
    episode_id: str
    ok: bool
    source_count: int
    ok_count: int
    missing_count: int
    changed_count: int
    results: list[EpisodeSourceVerifyResultWire] = field(default_factory=list)


from sase.core.episode_wire_conversion import (  # noqa: E402
    episode_verify_report_from_dict,
    episode_wire_from_dict,
    episode_wire_to_json_dict,
)

__all__ = [
    "EPISODE_WIRE_SCHEMA_VERSION",
    "EpisodeBuildReportWire",
    "EpisodeBuildRequestWire",
    "EpisodeEdgeWire",
    "EpisodeEventWire",
    "EpisodeLessonWire",
    "EpisodeNodeWire",
    "EpisodeSourceRefWire",
    "EpisodeSourceVerifyResultWire",
    "EpisodeStorageIndexRowWire",
    "EpisodeVerifyReportWire",
    "EpisodeWire",
    "episode_verify_report_from_dict",
    "episode_wire_from_dict",
    "episode_wire_to_json_dict",
]
