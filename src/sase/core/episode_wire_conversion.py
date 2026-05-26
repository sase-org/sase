"""JSON-shape conversion helpers for the episode wire."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from sase.core.episode_wire import (
    EpisodeEdgeWire,
    EpisodeEventWire,
    EpisodeLessonWire,
    EpisodeNodeWire,
    EpisodeSourceRefWire,
    EpisodeSourceVerifyResultWire,
    EpisodeVerifyReportWire,
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
    _expect_keys(
        data,
        {
            "schema_version",
            "episode_id",
            "project",
            "title",
            "summary",
            "root_source_id",
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
        schema_version=int(data["schema_version"]),
        episode_id=str(data["episode_id"]),
        project=str(data["project"]),
        title=str(data["title"]),
        summary=str(data["summary"]),
        root_source_id=str(data["root_source_id"]),
        sources=[_source_from_dict(item) for item in data.get("sources") or []],
        nodes=[_node_from_dict(item) for item in data.get("nodes") or []],
        edges=[_edge_from_dict(item) for item in data.get("edges") or []],
        events=[_event_from_dict(item) for item in data.get("events") or []],
        lessons=[_lesson_from_dict(item) for item in data.get("lessons") or []],
        metadata=_str_map(data.get("metadata") or {}),
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


def _str_map(value: dict[str, Any]) -> dict[str, str]:
    return {str(key): str(val) for key, val in value.items()}


__all__ = [
    "episode_verify_report_from_dict",
    "episode_wire_from_dict",
    "episode_wire_to_json_dict",
]
