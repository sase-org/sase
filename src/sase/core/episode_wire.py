"""Wire records for deterministic episodic-memory episodes.

These dataclasses mirror ``sase_core::episode`` and define the stable
Python/Rust boundary for Phase 1 of the structured episode MVP.
"""

from __future__ import annotations

from dataclasses import dataclass, field

EPISODE_WIRE_SCHEMA_VERSION = 2


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
class EpisodeImportanceFactorWire:
    kind: str
    label: str
    score: int = 0
    evidence_ids: list[str] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EpisodeSafetyWire:
    untrusted_transcript_text: bool = False
    prompt_injection_phrase_hits: list[str] = field(default_factory=list)
    redaction_hits: list[str] = field(default_factory=list)
    private_or_missing_source_flags: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EpisodeWeakRefsWire:
    changespec_names: list[str] = field(default_factory=list)
    bead_ids: list[str] = field(default_factory=list)
    agent_families: list[str] = field(default_factory=list)
    touched_paths: list[str] = field(default_factory=list)
    metadata: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class EpisodeWire:
    schema_version: int
    episode_id: str
    project: str
    title: str
    summary: str
    root_source_id: str
    component_key: str = ""
    component_root_kind: str = ""
    status: str = "active"
    importance_score: int = 0
    importance_band: str = "unknown"
    importance_factors: list[EpisodeImportanceFactorWire] = field(default_factory=list)
    safety: EpisodeSafetyWire = field(default_factory=EpisodeSafetyWire)
    weak_refs: EpisodeWeakRefsWire = field(default_factory=EpisodeWeakRefsWire)
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
    content_sha256: str
    component_key: str = ""
    status: str = "active"
    summary_excerpt: str = ""
    chat_count: int = 0
    agent_count: int = 0
    importance_score: int = 0
    importance_band: str = "unknown"
    lesson_path: str = ""
    legacy_lesson_path: str | None = None
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
    episode_storage_index_row_from_dict,
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
    "EpisodeImportanceFactorWire",
    "EpisodeLessonWire",
    "EpisodeNodeWire",
    "EpisodeSafetyWire",
    "EpisodeSourceRefWire",
    "EpisodeSourceVerifyResultWire",
    "EpisodeStorageIndexRowWire",
    "EpisodeVerifyReportWire",
    "EpisodeWeakRefsWire",
    "EpisodeWire",
    "episode_storage_index_row_from_dict",
    "episode_verify_report_from_dict",
    "episode_wire_from_dict",
    "episode_wire_to_json_dict",
]
