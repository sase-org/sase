"""Shared helpers for the ``sase artifact`` CLI."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import NoReturn

from sase.core.artifact_wire import (
    ARTIFACT_WIRE_SCHEMA_VERSION,
    ArtifactMutationResultWire,
    artifact_wire_to_json_dict,
)


def default_artifact_index_path() -> Path:
    """Return the default unified artifact SQLite index path."""
    return Path.home() / ".sase" / "artifacts.sqlite"


def index_path(args: object) -> Path:
    value = getattr(args, "index", None)
    if value:
        return Path(value).expanduser()
    return default_artifact_index_path()


def emit_json(value: object) -> NoReturn:
    emit_json_with_exit(value, exit_code=0)


def emit_json_with_exit(value: object, *, exit_code: int) -> NoReturn:
    print(
        json.dumps(
            artifact_wire_to_json_dict(value),
            indent=2,
            sort_keys=True,
        )
    )
    sys.exit(exit_code)


def emit_mutation_result(
    result: ArtifactMutationResultWire, *, json_output: bool
) -> NoReturn:
    if json_output:
        emit_json(result)
    print(f"operation: {result.operation}")
    print(
        "counts: "
        f"nodes +{result.nodes_added} ~{result.nodes_updated} -{result.nodes_removed}, "
        f"links +{result.links_added} ~{result.links_updated} -{result.links_removed}, "
        f"tombstones +{result.tombstones_added}"
    )
    for label, values in (
        ("affected nodes", result.affected_node_ids),
        ("affected links", result.affected_link_ids),
        ("tombstones", result.tombstone_ids),
    ):
        if values:
            print(f"{label}: {', '.join(values)}")
    if result.errors:
        print("errors:")
        for error in result.errors:
            print(f"  - {error}")
    sys.exit(0)


def json_value(raw: str, label: str) -> object:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"malformed {label}: {exc.msg}") from exc


def json_object(raw: str | None, label: str) -> dict[str, object]:
    if raw is None:
        return {}
    value = json_value(raw, label)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def merge_mutation_results(
    operation: str,
    results: list[ArtifactMutationResultWire],
) -> ArtifactMutationResultWire:
    return ArtifactMutationResultWire(
        schema_version=ARTIFACT_WIRE_SCHEMA_VERSION,
        operation=operation,
        nodes_added=sum(result.nodes_added for result in results),
        nodes_updated=sum(result.nodes_updated for result in results),
        nodes_removed=sum(result.nodes_removed for result in results),
        links_added=sum(result.links_added for result in results),
        links_updated=sum(result.links_updated for result in results),
        links_removed=sum(result.links_removed for result in results),
        tombstones_added=sum(result.tombstones_added for result in results),
        affected_node_ids=_unique(
            node_id for result in results for node_id in result.affected_node_ids
        ),
        affected_link_ids=_unique(
            link_id for result in results for link_id in result.affected_link_ids
        ),
        tombstone_ids=_unique(
            tombstone_id for result in results for tombstone_id in result.tombstone_ids
        ),
        errors=[error for result in results for error in result.errors],
    )


def _unique(values: Iterable[object]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        text = str(value)
        if text in seen:
            continue
        seen.add(text)
        unique_values.append(text)
    return unique_values
