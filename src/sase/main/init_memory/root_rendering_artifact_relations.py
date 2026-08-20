"""Artifact-relation memory-note and registry snapshot rendering."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from pathlib import Path
from typing import Any

from sase.amd.inline_memory import validate_short_memory_structure
from sase.content_layout import resolve_project_layout
from sase.mdtemplates import render_markdown_template
from sase.memory.notes import AGENTS_PARENT, apply_memory_frontmatter
from sase.memory.paths import CANONICAL_MEMORY_RELATIVE_ROOT
from sase.sdd.artifact_link_store import assembled_artifact_relations

from .formatting import format_generated_memory_markdown

MEMORY_SASE_ARTIFACT_RELATIONS_TEMPLATE_FILENAME = (
    "memory-sase-artifact-relations.template.md"
)
_MEMORY_TEMPLATE_PACKAGE = "sase.main.init_memory"
_MEMORY_SASE_ARTIFACT_RELATIONS_TEMPLATE_VARS = frozenset(
    {"artifact_relation_rows", "reserved_relation_rows"}
)
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


def generated_artifact_relations_memory_relative_path() -> Path:
    """Return the generated ``sase/memory/artifact_relations.md`` path."""

    return CANONICAL_MEMORY_RELATIVE_ROOT / "artifact_relations.md"


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


def render_generated_artifact_relations_memory_body() -> tuple[str | None, str | None]:
    """Render ``sase/memory/artifact_relations.md`` or return a blocker."""

    relations = assembled_artifact_relations()
    rendered, render_error = render_markdown_template(
        package=_MEMORY_TEMPLATE_PACKAGE,
        filename=f"templates/{MEMORY_SASE_ARTIFACT_RELATIONS_TEMPLATE_FILENAME}",
        required_variables=_MEMORY_SASE_ARTIFACT_RELATIONS_TEMPLATE_VARS,
        context={
            "artifact_relation_rows": _render_artifact_relation_rows(relations),
            "reserved_relation_rows": _render_reserved_relation_rows(
                _RESERVED_RELATIONS
            ),
        },
    )
    if render_error is not None or rendered is None:
        return (
            None,
            render_error
            or "failed to render sase/memory/artifact_relations.md template",
        )
    formatted = format_generated_memory_markdown(rendered)
    structure_error = validate_short_memory_structure(formatted)
    if structure_error is not None:
        return (
            None,
            f"packaged {MEMORY_SASE_ARTIFACT_RELATIONS_TEMPLATE_FILENAME}: "
            f"{structure_error}",
        )
    return formatted, None


def generated_artifact_relations_memory_content(
    generated_artifact_relations_body: str,
) -> str:
    """Return the generated artifact-relations memory note with frontmatter."""

    return apply_memory_frontmatter(
        generated_artifact_relations_body,
        note_type="short",
        parent=AGENTS_PARENT,
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
