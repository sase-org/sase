"""Task-type generated memory-web and catalog snapshot rendering."""

from __future__ import annotations

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
    committed_task_type_records,
    get_task_type_registry,
    render_task_type_snapshot_json,
    task_type_snapshot_entry,
)
from sase.task_types._models import TaskTypeRecord
from sase.task_types.detail import (
    TaskTypeDetail,
    TaskTypeFieldDetail,
    TaskTypeFieldValidatorDetail,
    task_type_detail,
)

from .formatting import format_generated_memory_markdown

TASK_TYPES_WEB_SLUG = "task_types"
MEMORY_SASE_TASK_TYPES_TEMPLATE_FILENAME = "memory-sase-task-types.template.md"
_MEMORY_TEMPLATE_PACKAGE = "sase.main.init_memory"
_TASK_TYPES_NOTE_TITLE_HEADING = "# Task Bead Types"
_LEGACY_TASK_TYPES_NOTE_TYPES_HEADING = "## Types"
_GENERATED_TASK_TYPE_STRAND_SIGNATURE = "sase.task_types.generated-strand.v1"


def generated_task_types_memory_relative_path() -> Path:
    """Return the generated ``sase/memory/task_types.md`` root-relative path."""
    return CANONICAL_MEMORY_RELATIVE_ROOT / f"{TASK_TYPES_WEB_SLUG}.md"


def generated_task_type_snapshot_path(root: Path) -> Path:
    """Return the committed catalog snapshot path (D6), outside ``sase/memory``."""
    return resolve_project_layout(root).namespace_root.path / "task_types.json"


def _task_type_strand_pointer_line(slug: str) -> str:
    return (
        f"Run `sase bead task-type show {slug}` for the full field list, "
        "validators, and body template."
    )


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _code(value: object) -> str:
    return f"`{value}`"


def _code_or_none(value: str) -> str:
    return _code(value) if value else "(none)"


def _roles_markdown(field: TaskTypeFieldDetail) -> str:
    return ", ".join(_code(role) for role in field.roles) or "(none)"


def _validator_value_markdown(validator: TaskTypeFieldValidatorDetail) -> str:
    if validator.name == "values" and isinstance(validator.value, list):
        return ", ".join(_code(item) for item in validator.value) or "(none)"
    return _code(validator.value)


def _field_markdown(field: TaskTypeFieldDetail) -> list[str]:
    lines = [
        f"**Field `{field.name}`**",
        "",
        f"- Name: `{field.name}`",
        f"- Label: {field.label or '(none)'}",
        f"- Type: `{field.type}`",
        f"- Required: {_yes_no(field.required)}",
        f"- Roles: {_roles_markdown(field)}",
        f"- Help: {field.help or '(none)'}",
    ]
    if field.validators:
        lines.extend(
            f"- Validator `{validator.name}`: {_validator_value_markdown(validator)}"
            for validator in field.validators
        )
    else:
        lines.append("- Validators: (none)")
    return lines


def _body_template_markdown(template: str) -> list[str]:
    if not template.strip():
        return ["(none)"]
    return ["```markdown", template.rstrip("\n"), "```"]


def _render_task_type_strand_body(detail: TaskTypeDetail) -> str:
    lines = [
        "## Identity",
        "",
        f"- Task type: `{detail.task_type}`",
        f"- Label: {detail.label}",
        f"- Glyph: {detail.glyph}",
        f"- Accent color: {_code_or_none(detail.accent_color)}",
        f"- Agent creatable: {_yes_no(detail.agent_creatable)}",
        f"- Show schema version: `{detail.schema_version}`",
        f"- Digest: `{detail.digest}`",
        "",
        "## Summary",
        "",
        detail.summary or "(none)",
        "",
        "## When To Use",
        "",
        detail.when_to_use or "(none)",
    ]
    if detail.create_refusal:
        lines.extend(["", "## Create Refusal", "", detail.create_refusal])
    lines.extend(["", "## Fields", ""])
    if detail.fields:
        for index, field in enumerate(detail.fields):
            if index:
                lines.append("")
            lines.extend(_field_markdown(field))
    else:
        lines.append("(none)")
    lines.extend(
        [
            "",
            "## Body Template",
            "",
            *_body_template_markdown(detail.body_template),
            "",
            "## Triage",
            "",
            f"- min_plus_ones: `{detail.triage.min_plus_ones}`",
            "",
            "## Provenance",
            "",
            f"- Provenance label: `{detail.provenance.label}`",
            f"- Source: `{detail.provenance.source}`",
            f"- Package: `{detail.provenance.package}`",
            f"- Version: `{detail.provenance.version}`",
        ]
    )
    return "\n".join(lines) + "\n"


def _render_task_type_strand_content(record: TaskTypeRecord) -> str:
    """Render one generated strand file's full content for *record*."""
    detail = task_type_detail(record)
    summary = collapse_description(detail.summary) or detail.label
    frontmatter = render_frontmatter_block(
        {
            "keyword": detail.label,
            "summary": summary,
            "metadata": {
                "generated_by": _GENERATED_TASK_TYPE_STRAND_SIGNATURE,
                "task_type": detail.task_type,
            },
        }
    )
    body = format_generated_memory_markdown(_render_task_type_strand_body(detail))
    return frontmatter + body


def _project_task_type_records() -> tuple[TaskTypeRecord, ...]:
    """Return the committed catalog this project's generated files may document.

    Builtins, project-config types, and types from ``plugins.required``
    distributions are included. Optional plugin types stay live-only so two
    machines with different optional plugin sets render the same web and
    ``sase/task_types.json``.
    """
    records = committed_task_type_records(get_task_type_registry())
    return tuple(sorted(records, key=lambda record: record.task_type))


def _project_task_type_snapshot_entries() -> tuple[dict[str, Any], ...]:
    return tuple(
        task_type_snapshot_entry(record) for record in _project_task_type_records()
    )


def _agent_creatable_task_type_records() -> tuple[TaskTypeRecord, ...]:
    return tuple(
        record for record in _project_task_type_records() if record.agent_creatable
    )


def current_agent_creatable_task_type_slugs() -> frozenset[str]:
    """Return the committed, agent-creatable task-type slugs SASE now generates."""
    return frozenset(
        record.task_type for record in _agent_creatable_task_type_records()
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
            slug=record.task_type,
            content=_render_task_type_strand_content(record),
        )
        for record in _agent_creatable_task_type_records()
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

    New strands carry an explicit frontmatter signature. The legacy pointer
    line is also checked against whitespace-collapsed text because
    ``format_generated_memory_markdown`` may hard-wrap it across lines.
    """
    if _GENERATED_TASK_TYPE_STRAND_SIGNATURE in text and f"task_type: {slug}" in text:
        return True
    normalized = " ".join(text.split())
    return _task_type_strand_pointer_line(slug) in normalized


def render_generated_task_type_snapshot_json() -> tuple[str | None, str | None]:
    """Render the committed ``sase/task_types.json`` catalog snapshot (D6)."""
    entries = _project_task_type_snapshot_entries()
    try:
        return render_task_type_snapshot_json(entries), None
    except Exception as exc:
        return None, f"failed to render sase/task_types.json snapshot: {exc}"
