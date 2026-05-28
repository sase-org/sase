"""JSON-shape conversion helpers for the episode wire."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from sase.core.episode_wire import (
    EPISODE_WIRE_SCHEMA_VERSION,
    EpisodeEdgeWire,
    EpisodeEventWire,
    EpisodeImportanceFactorWire,
    EpisodeLessonWire,
    EpisodeNodeWire,
    EpisodeSafetyWire,
    EpisodeSourceRefWire,
    EpisodeSourceVerifyResultWire,
    EpisodeStorageIndexRowWire,
    EpisodeVerifyReportWire,
    EpisodeWeakRefsWire,
    EpisodeWire,
)


def episode_wire_to_json_dict(record: Any) -> Any:
    """Project episode wire records to a JSON-safe shape."""
    if isinstance(record, (list, tuple)):
        return [episode_wire_to_json_dict(item) for item in record]
    if isinstance(record, dict):
        return {k: episode_wire_to_json_dict(v) for k, v in record.items()}
    if hasattr(record, "__dataclass_fields__"):
        return asdict(record)
    return record


def episode_wire_from_dict(data: dict[str, Any]) -> EpisodeWire:
    schema_version = int(data.get("schema_version", 1))
    _expect_keys(
        data,
        {
            "schema_version",
            "episode_id",
            "project",
            "title",
            "summary",
            "root_source_id",
            "component_key",
            "component_root_kind",
            "status",
            "importance_score",
            "importance_band",
            "importance_factors",
            "safety",
            "weak_refs",
            "sources",
            "nodes",
            "edges",
            "events",
            "lessons",
            "metadata",
        },
        "EpisodeWire",
    )
    return EpisodeWire(
        schema_version=schema_version,
        episode_id=str(data["episode_id"]),
        project=str(data["project"]),
        title=str(data["title"]),
        summary=str(data["summary"]),
        root_source_id=str(data["root_source_id"]),
        component_key=str(data.get("component_key") or ""),
        component_root_kind=str(data.get("component_root_kind") or ""),
        status=str(
            data.get("status")
            or ("legacy" if schema_version < EPISODE_WIRE_SCHEMA_VERSION else "active")
        ),
        importance_score=int(data.get("importance_score") or 0),
        importance_band=str(data.get("importance_band") or "unknown"),
        importance_factors=[
            _importance_factor_from_dict(item)
            for item in data.get("importance_factors") or []
        ],
        safety=_safety_from_dict(data.get("safety") or {}),
        weak_refs=_weak_refs_from_dict(data.get("weak_refs") or {}),
        sources=[_source_from_dict(item) for item in data.get("sources") or []],
        nodes=[_node_from_dict(item) for item in data.get("nodes") or []],
        edges=[_edge_from_dict(item) for item in data.get("edges") or []],
        events=[_event_from_dict(item) for item in data.get("events") or []],
        lessons=[_lesson_from_dict(item) for item in data.get("lessons") or []],
        metadata=_str_map(data.get("metadata") or {}),
    )


def episode_storage_index_row_from_dict(
    data: dict[str, Any],
) -> EpisodeStorageIndexRowWire:
    schema_version = int(data.get("schema_version", 1))
    _expect_keys(
        data,
        {
            "schema_version",
            "episode_id",
            "project",
            "title",
            "component_key",
            "status",
            "summary_excerpt",
            "first_event_at",
            "last_event_at",
            "importance_score",
            "importance_band",
            "root_agent_names",
            "chat_count",
            "agent_count",
            "source_count",
            "content_sha256",
            "lesson_path",
            "legacy_lesson_path",
            "changespec_name",
            "bead_ids",
            "outcome",
        },
        "EpisodeStorageIndexRowWire",
    )
    lesson_path = _optional_str(data.get("lesson_path")) or ""
    legacy_lesson_path = _optional_str(data.get("legacy_lesson_path"))
    if schema_version < EPISODE_WIRE_SCHEMA_VERSION and legacy_lesson_path is None:
        legacy_lesson_path = lesson_path or None
    return EpisodeStorageIndexRowWire(
        schema_version=schema_version,
        episode_id=str(data["episode_id"]),
        project=str(data["project"]),
        title=str(data["title"]),
        source_count=int(data["source_count"]),
        content_sha256=str(data["content_sha256"]),
        component_key=str(data.get("component_key") or ""),
        status=str(
            data.get("status")
            or ("legacy" if schema_version < EPISODE_WIRE_SCHEMA_VERSION else "active")
        ),
        summary_excerpt=str(data.get("summary_excerpt") or ""),
        chat_count=int(data.get("chat_count") or 0),
        agent_count=int(data.get("agent_count") or 0),
        importance_score=int(data.get("importance_score") or 0),
        importance_band=str(data.get("importance_band") or "unknown"),
        lesson_path=lesson_path,
        legacy_lesson_path=legacy_lesson_path,
        root_agent_names=_strings(data.get("root_agent_names")),
        changespec_name=_optional_str(data.get("changespec_name")),
        bead_ids=_strings(data.get("bead_ids")),
        outcome=_optional_str(data.get("outcome")),
        first_event_at=_optional_str(data.get("first_event_at")),
        last_event_at=_optional_str(data.get("last_event_at")),
    )


def episode_verify_report_from_dict(
    data: dict[str, Any],
) -> EpisodeVerifyReportWire:
    _expect_keys(
        data,
        {
            "schema_version",
            "episode_id",
            "ok",
            "source_count",
            "ok_count",
            "missing_count",
            "changed_count",
            "results",
        },
        "EpisodeVerifyReportWire",
    )
    return EpisodeVerifyReportWire(
        schema_version=int(data["schema_version"]),
        episode_id=str(data["episode_id"]),
        ok=bool(data["ok"]),
        source_count=int(data["source_count"]),
        ok_count=int(data["ok_count"]),
        missing_count=int(data["missing_count"]),
        changed_count=int(data["changed_count"]),
        results=[_verify_result_from_dict(item) for item in data.get("results") or []],
    )


def _source_from_dict(data: dict[str, Any]) -> EpisodeSourceRefWire:
    _expect_keys(
        data,
        {"id", "kind", "path", "label", "exists", "size_bytes", "sha256"},
        "EpisodeSourceRefWire",
    )
    return EpisodeSourceRefWire(
        id=str(data["id"]),
        kind=str(data["kind"]),
        path=str(data["path"]),
        label=_optional_str(data.get("label")),
        exists=bool(data.get("exists", False)),
        size_bytes=_optional_int(data.get("size_bytes")),
        sha256=_optional_str(data.get("sha256")),
    )


def _node_from_dict(data: dict[str, Any]) -> EpisodeNodeWire:
    _expect_keys(
        data,
        {"id", "kind", "label", "source_id", "metadata"},
        "EpisodeNodeWire",
    )
    return EpisodeNodeWire(
        id=str(data["id"]),
        kind=str(data["kind"]),
        label=_optional_str(data.get("label")),
        source_id=_optional_str(data.get("source_id")),
        metadata=_str_map(data.get("metadata") or {}),
    )


def _edge_from_dict(data: dict[str, Any]) -> EpisodeEdgeWire:
    _expect_keys(
        data,
        {
            "id",
            "from_node_id",
            "to_node_id",
            "kind",
            "evidence_ids",
            "metadata",
        },
        "EpisodeEdgeWire",
    )
    return EpisodeEdgeWire(
        id=str(data["id"]),
        from_node_id=str(data["from_node_id"]),
        to_node_id=str(data["to_node_id"]),
        kind=str(data["kind"]),
        evidence_ids=[str(item) for item in data.get("evidence_ids") or []],
        metadata=_str_map(data.get("metadata") or {}),
    )


def _event_from_dict(data: dict[str, Any]) -> EpisodeEventWire:
    _expect_keys(
        data,
        {
            "id",
            "kind",
            "timestamp",
            "title",
            "description",
            "evidence_ids",
        },
        "EpisodeEventWire",
    )
    return EpisodeEventWire(
        id=str(data["id"]),
        kind=str(data["kind"]),
        timestamp=_optional_str(data.get("timestamp")),
        title=str(data["title"]),
        description=_optional_str(data.get("description")),
        evidence_ids=[str(item) for item in data.get("evidence_ids") or []],
    )


def _lesson_from_dict(data: dict[str, Any]) -> EpisodeLessonWire:
    _expect_keys(
        data,
        {"id", "kind", "text", "evidence_ids", "source_confidence"},
        "EpisodeLessonWire",
    )
    return EpisodeLessonWire(
        id=str(data["id"]),
        kind=str(data["kind"]),
        text=str(data["text"]),
        evidence_ids=[str(item) for item in data.get("evidence_ids") or []],
        source_confidence=str(data.get("source_confidence") or "deterministic"),
    )


def _importance_factor_from_dict(
    data: dict[str, Any],
) -> EpisodeImportanceFactorWire:
    _expect_keys(
        data,
        {"kind", "label", "score", "evidence_ids", "metadata"},
        "EpisodeImportanceFactorWire",
    )
    return EpisodeImportanceFactorWire(
        kind=str(data["kind"]),
        label=str(data["label"]),
        score=int(data.get("score") or 0),
        evidence_ids=[str(item) for item in data.get("evidence_ids") or []],
        metadata=_str_map(data.get("metadata") or {}),
    )


def _safety_from_dict(data: dict[str, Any]) -> EpisodeSafetyWire:
    _expect_keys(
        data,
        {
            "untrusted_transcript_text",
            "prompt_injection_phrase_hits",
            "redaction_hits",
            "private_or_missing_source_flags",
            "warnings",
        },
        "EpisodeSafetyWire",
    )
    return EpisodeSafetyWire(
        untrusted_transcript_text=bool(data.get("untrusted_transcript_text", False)),
        prompt_injection_phrase_hits=_strings(data.get("prompt_injection_phrase_hits")),
        redaction_hits=_strings(data.get("redaction_hits")),
        private_or_missing_source_flags=_strings(
            data.get("private_or_missing_source_flags")
        ),
        warnings=_strings(data.get("warnings")),
    )


def _weak_refs_from_dict(data: dict[str, Any]) -> EpisodeWeakRefsWire:
    _expect_keys(
        data,
        {
            "changespec_names",
            "bead_ids",
            "agent_families",
            "touched_paths",
            "metadata",
        },
        "EpisodeWeakRefsWire",
    )
    return EpisodeWeakRefsWire(
        changespec_names=_strings(data.get("changespec_names")),
        bead_ids=_strings(data.get("bead_ids")),
        agent_families=_strings(data.get("agent_families")),
        touched_paths=_strings(data.get("touched_paths")),
        metadata=_str_list_map(data.get("metadata") or {}),
    )


def _verify_result_from_dict(
    data: dict[str, Any],
) -> EpisodeSourceVerifyResultWire:
    _expect_keys(
        data,
        {
            "source_id",
            "path",
            "expected_exists",
            "actual_exists",
            "expected_size_bytes",
            "actual_size_bytes",
            "expected_sha256",
            "actual_sha256",
            "status",
        },
        "EpisodeSourceVerifyResultWire",
    )
    return EpisodeSourceVerifyResultWire(
        source_id=str(data["source_id"]),
        path=str(data["path"]),
        expected_exists=bool(data["expected_exists"]),
        actual_exists=bool(data["actual_exists"]),
        expected_size_bytes=_optional_int(data.get("expected_size_bytes")),
        actual_size_bytes=_optional_int(data.get("actual_size_bytes")),
        expected_sha256=_optional_str(data.get("expected_sha256")),
        actual_sha256=_optional_str(data.get("actual_sha256")),
        status=str(data["status"]),
    )


def _expect_keys(
    data: dict[str, Any],
    allowed: set[str],
    label: str,
) -> None:
    extra = set(data) - allowed
    if extra:
        joined = ", ".join(sorted(extra))
        raise TypeError(f"{label} has unknown keys: {joined}")


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _str_map(value: dict[str, Any]) -> dict[str, str]:
    return {str(key): str(val) for key, val in value.items()}


def _str_list_map(value: dict[str, Any]) -> dict[str, list[str]]:
    return {str(key): _strings(val) for key, val in value.items()}


__all__ = [
    "episode_storage_index_row_from_dict",
    "episode_verify_report_from_dict",
    "episode_wire_from_dict",
    "episode_wire_to_json_dict",
]
