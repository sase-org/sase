"""Task-type generated memory-web and catalog snapshot rendering."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.amd.inline_memory import validate_short_memory_structure
from sase.content_layout import resolve_project_layout
from sase.mdtemplates import render_markdown_template
from sase.memory.notes import (
    AGENTS_PARENT,
    apply_memory_frontmatter,
    collapse_description,
    parse_memory_note_text,
    render_frontmatter_block,
)
from sase.memory.paths import CANONICAL_MEMORY_RELATIVE_ROOT
from sase.memory.web import (
    GeneratedMemoryWebProvider,
    GeneratedStrandSource,
    GeneratedWebSource,
    MemoryWeb,
)
from sase.task_types import (
    build_committed_task_type_snapshot_entries,
    get_task_type_registry,
    render_task_type_snapshot_json,
)

from .formatting import format_generated_memory_markdown

TASK_TYPES_WEB_SLUG = "task_types"
MEMORY_SASE_TASK_TYPES_TEMPLATE_FILENAME = "memory-sase-task-types.template.md"
_MEMORY_TEMPLATE_PACKAGE = "sase.main.init_memory"
_TASK_TYPES_NOTE_TITLE_HEADING = "# Task Bead Types"
_LEGACY_TASK_TYPES_NOTE_TYPES_HEADING = "## Types"


def generated_task_types_memory_relative_path() -> Path:
    """Return the generated ``sase/memory/task_types.md`` root-relative path."""
    return CANONICAL_MEMORY_RELATIVE_ROOT / f"{TASK_TYPES_WEB_SLUG}.md"


def generated_task_type_snapshot_path(root: Path) -> Path:
    """Return the committed catalog snapshot path (D6), outside ``sase/memory``."""
    return resolve_project_layout(root).namespace_root.path / "task_types.json"


def _task_type_field_names(
    spec: Mapping[str, Any],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return ``(required_names, optional_names)`` for one task-type spec."""
    raw_fields = spec.get("fields")
    fields = raw_fields if isinstance(raw_fields, list) else ()
    required = tuple(
        str(field["name"])
        for field in fields
        if isinstance(field, Mapping) and field.get("required")
    )
    optional = tuple(
        str(field["name"])
        for field in fields
        if isinstance(field, Mapping) and not field.get("required")
    )
    return required, optional


def _task_type_strand_pointer_line(slug: str) -> str:
    return (
        f"Run `sase bead task-type show {slug}` for the full field list, "
        "validators, and body template."
    )


def _render_task_type_strand_body(spec: Mapping[str, Any]) -> str:
    slug = str(spec.get("task_type", ""))
    when_to_use = str(spec.get("when_to_use") or "")
    required, optional = _task_type_field_names(spec)
    paragraphs = [when_to_use]
    bullets = []
    if required:
        names = ", ".join(f"`{name}`" for name in required)
        bullets.append(f"- Required fields: {names}")
    if optional:
        names = ", ".join(f"`{name}`" for name in optional)
        bullets.append(f"- Optional fields: {names}")
    if bullets:
        paragraphs.append("\n".join(bullets))
    paragraphs.append(_task_type_strand_pointer_line(slug))
    return "\n\n".join(paragraphs) + "\n"


def _render_task_type_strand_content(spec: Mapping[str, Any]) -> str:
    """Render one generated strand file's full content for *spec*."""
    label = str(spec.get("label") or spec.get("task_type", ""))
    summary = collapse_description(str(spec.get("summary") or "")) or label
    body = format_generated_memory_markdown(_render_task_type_strand_body(spec))
    return render_frontmatter_block({"keyword": label, "summary": summary}) + body


def _project_task_type_snapshot_entries() -> tuple[dict[str, Any], ...]:
    """Return the committed catalog this project's snapshot may document.

    Builtins, project-config types, and types from ``plugins.required``
    distributions are included. Optional plugin types stay live-only so two
    machines with different optional plugin sets render the same web and
    ``sase/task_types.json``.
    """
    return build_committed_task_type_snapshot_entries(get_task_type_registry())


def _agent_creatable_task_type_specs() -> tuple[dict[str, Any], ...]:
    specs = _project_task_type_snapshot_entries()
    creatable = tuple(spec for spec in specs if spec.get("agent_creatable", True))
    return tuple(sorted(creatable, key=lambda spec: str(spec.get("task_type", ""))))


def current_agent_creatable_task_type_slugs() -> frozenset[str]:
    """Return the committed, agent-creatable task-type slugs SASE now generates."""
    return frozenset(
        str(spec.get("task_type", "")) for spec in _agent_creatable_task_type_specs()
    )


def _render_task_types_descriptor_content() -> tuple[str | None, str | None]:
    rendered, render_error = render_markdown_template(
        package=_MEMORY_TEMPLATE_PACKAGE,
        filename=f"templates/{MEMORY_SASE_TASK_TYPES_TEMPLATE_FILENAME}",
        required_variables=frozenset(),
        context={},
    )
    if render_error is not None or rendered is None:
        return (
            None,
            render_error or "failed to render sase/memory/task_types.md template",
        )
    formatted = format_generated_memory_markdown(rendered)
    structure_error = validate_short_memory_structure(formatted)
    if structure_error is not None:
        return (
            None,
            f"packaged {MEMORY_SASE_TASK_TYPES_TEMPLATE_FILENAME}: {structure_error}",
        )
    return (
        apply_memory_frontmatter(
            formatted,
            note_type="core",
            parent=AGENTS_PARENT,
            extra={"web": True, "roster": "list", "strand_noun": "task type"},
        ),
        None,
    )


def _render_generated_task_types_web_sources() -> tuple[
    GeneratedWebSource | None, str | None
]:
    """Render the in-memory generated task-types web source, or return a blocker."""
    descriptor_content, descriptor_error = _render_task_types_descriptor_content()
    if descriptor_error is not None or descriptor_content is None:
        return None, descriptor_error

    strands = tuple(
        GeneratedStrandSource(
            slug=str(spec.get("task_type", "")),
            content=_render_task_type_strand_content(spec),
        )
        for spec in _agent_creatable_task_type_specs()
    )
    return (
        GeneratedWebSource(
            slug=TASK_TYPES_WEB_SLUG,
            descriptor_content=descriptor_content,
            strands=strands,
        ),
        None,
    )


def build_generated_task_types_web(root: Path) -> tuple[MemoryWeb | None, str | None]:
    """Return the generated ``task_types`` memory web for *root*, or a blocker.

    Always targets the canonical ``sase/memory`` write root, even when *root*
    still has a pre-migration legacy tree: a generated web has no existing
    content to read, unlike a file-backed one.
    """
    source, error = _render_generated_task_types_web_sources()
    if error is not None or source is None:
        return None, error
    discovery = GeneratedMemoryWebProvider(source).discover(root)
    return discovery.webs[0], None


def is_generated_task_types_memory_content(text: str) -> bool:
    """Return whether *text* matches a generated task-type memory descriptor.

    Recognition is a heading (and, for current output, a ``web: true``)
    signature rather than a byte comparison against a re-render: a previously
    written home body depended on that machine's task-type catalog and on
    whichever template shipped when it was last generated. The legacy
    (pre-web) shape is still recognized so an older leftover keeps retiring
    cleanly.
    """
    note = parse_memory_note_text(text, generated_task_types_memory_relative_path())
    if note.type != "core":
        return False
    headings = set(note.body.splitlines())
    if _TASK_TYPES_NOTE_TITLE_HEADING not in headings:
        return False
    if note.frontmatter.get("web") is True:
        return True
    return _LEGACY_TASK_TYPES_NOTE_TYPES_HEADING in headings


def is_generated_task_type_strand_content(slug: str, text: str) -> bool:
    """Return whether *text* matches a generated task-type strand for *slug*.

    The pointer line is checked against whitespace-collapsed text because
    ``format_generated_memory_markdown`` may hard-wrap it across lines.
    """
    normalized = " ".join(text.split())
    return _task_type_strand_pointer_line(slug) in normalized


def render_generated_task_type_snapshot_json() -> tuple[str | None, str | None]:
    """Render the committed ``sase/task_types.json`` catalog snapshot (D6)."""
    entries = _project_task_type_snapshot_entries()
    try:
        return render_task_type_snapshot_json(entries), None
    except Exception as exc:
        return None, f"failed to render sase/task_types.json snapshot: {exc}"
