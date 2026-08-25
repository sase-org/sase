"""Artifact-relation registry rendering for generated memory."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from pathlib import Path
from typing import Any

from sase.content_layout import resolve_project_layout
from sase.memory.notes import parse_memory_note_text
from sase.memory.paths import CANONICAL_MEMORY_RELATIVE_ROOT
from sase.sdd.artifact_link_store import assembled_artifact_relations

ARTIFACT_RELATIONS_MEMORY_RELATIVE_PATH = (
    CANONICAL_MEMORY_RELATIVE_ROOT / "artifact_relations.md"
)
ARTIFACT_RELATION_REGISTRY_TEMPLATE_VARS = frozenset(
    {"artifact_relation_rows", "reserved_relation_rows"}
)
_ARTIFACT_RELATIONS_NOTE_TITLE_HEADING = "# Artifact Relation Registry"
_RESERVED_RELATIONS = (
    {
        "slug": "blocks",
        "pointer": "sase bead dep",
    },
    {
        "slug": "depends-on",
        "pointer": "sase bead dep",
    },
)


def generated_artifact_relation_snapshot_path(root: Path) -> Path:
    """Return the committed artifact-relation registry snapshot path."""

    return resolve_project_layout(root).namespace_root.path / "artifact_relations.json"


def _relation_bool(value: object) -> str:
    return "yes" if bool(value) else "no"


def _render_artifact_relation_row(spec: Mapping[str, Any]) -> str:
    slug = str(spec.get("slug", ""))
    inverse = str(spec.get("inverse", ""))
    written_by = str(spec.get("written_by", ""))
    directed = _relation_bool(spec.get("directed"))
    return (
        f"- `{slug}`: inverse `{inverse}`, directed {directed}, "
        f"written by `{written_by}`."
    )


def _render_artifact_relation_rows(specs: Sequence[Mapping[str, Any]]) -> str:
    return "\n".join(_render_artifact_relation_row(spec) for spec in specs)


def _render_reserved_relation_rows(specs: Sequence[Mapping[str, Any]]) -> str:
    return "\n".join(
        f"- `{spec['slug']}`: use `{spec['pointer']}` instead." for spec in specs
    )


def artifact_relation_registry_template_context() -> tuple[
    Mapping[str, str] | None, str | None
]:
    """Return template context for the generated artifact relation registry."""
    try:
        relations = assembled_artifact_relations()
    except Exception as exc:
        return (
            None,
            f"failed to render artifact relation registry: {exc}",
        )
    return {
        "artifact_relation_rows": _render_artifact_relation_rows(relations),
        "reserved_relation_rows": _render_reserved_relation_rows(_RESERVED_RELATIONS),
    }, None


def is_generated_artifact_relations_memory_content(text: str) -> bool:
    """Return whether *text* matches the retired generated relation note."""
    note = parse_memory_note_text(text, ARTIFACT_RELATIONS_MEMORY_RELATIVE_PATH)
    return note.type == "core" and _ARTIFACT_RELATIONS_NOTE_TITLE_HEADING in set(
        note.body.splitlines()
    )


def render_generated_artifact_relation_snapshot_json() -> tuple[str | None, str | None]:
    """Render the committed ``sase/artifact_relations.json`` snapshot."""

    try:
        payload = {
            "schema_version": 1,
            "relations": [dict(entry) for entry in assembled_artifact_relations()],
            "reserved": [dict(entry) for entry in _RESERVED_RELATIONS],
        }
        return json.dumps(payload, indent=2) + "\n", None
    except Exception as exc:
        return None, f"failed to render sase/artifact_relations.json snapshot: {exc}"
