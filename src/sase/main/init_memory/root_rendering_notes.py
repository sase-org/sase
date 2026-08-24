"""Generated memory-note rendering helpers for memory root initialization."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from sase.agents_sync.rendering_markdown import md_escape
from sase.amd._config import resolve_markdown_template_override
from sase.amd.inline_memory import validate_short_memory_structure
from sase.mdtemplates import render_markdown_template
from sase.memory.notes import (
    AGENTS_PARENT,
    GeneratedLongMemoryNote,
    GeneratedShortMemoryNote,
    apply_memory_frontmatter,
    parse_memory_note_text,
)
from sase.memory.paths import (
    CANONICAL_MEMORY_RELATIVE_ROOT,
    canonical_memory_reference,
)

from .formatting import format_generated_memory_markdown
from .glossary import (
    GENERATED_GLOSSARY_MARKER_KEY,
    GENERATED_GLOSSARY_MARKER_VALUE,
    ProjectGlossaryTerms,
)
from .models import LinkedRepoMemoryEntry, MemoryExpectedFile
from .root_rendering_artifact_relations import (
    generated_artifact_relations_memory_relative_path,
)
from .root_rendering_task_types import generated_task_types_memory_relative_path

MEMORY_SASE_TEMPLATE_FILENAME = "memory-sase.template.md"
MEMORY_SASE_ARTIFACTS_TEMPLATE_FILENAME = "memory-sase-artifacts.template.md"
MEMORY_SASE_BEADS_TEMPLATE_FILENAME = "memory-sase-beads.template.md"
MEMORY_SASE_SIZES_TEMPLATE_FILENAME = "memory-sase-sizes.template.md"
MEMORY_SASE_GLOSSARY_TEMPLATE_FILENAME = "memory-sase-glossary.template.md"
_MEMORY_TEMPLATE_PACKAGE = "sase.main.init_memory"
_MEMORY_SASE_TEMPLATE_VARS = frozenset({"project_name", "linked_repo_entries"})
_MEMORY_SASE_GLOSSARY_TEMPLATE_VARS = frozenset({"glossary_term_entries"})
GENERATED_SASE_MEMORY_PRIORITY = 10


@dataclass(frozen=True)
class _GeneratedLongMemorySpec:
    template_filename: str
    relative_path: Path
    parent: str
    detail: str


def _linked_repo_list_item(entry: LinkedRepoMemoryEntry) -> str:
    return f"- `{entry.name}`: {entry.description}"


def _render_sase_memory(
    root: Path,
    entries: Iterable[LinkedRepoMemoryEntry],
    *,
    project_name: str | None = None,
) -> tuple[str | None, str | None]:
    override, resolve_error = resolve_markdown_template_override(
        root,
        memory_key="sase_template",
        legacy_key="memory_sase_template",
        user_filename=MEMORY_SASE_TEMPLATE_FILENAME,
    )
    if resolve_error is not None:
        return None, resolve_error
    rendered, render_error = render_markdown_template(
        package=_MEMORY_TEMPLATE_PACKAGE,
        filename=f"templates/{MEMORY_SASE_TEMPLATE_FILENAME}",
        required_variables=_MEMORY_SASE_TEMPLATE_VARS,
        context={
            "project_name": project_name or "",
            "linked_repo_entries": "\n".join(
                _linked_repo_list_item(entry) for entry in entries
            ),
        },
        override_path=override,
    )
    if render_error is not None or rendered is None:
        return None, render_error or "failed to render sase/memory/sase.md template"
    formatted = format_generated_memory_markdown(rendered)
    structure_error = validate_short_memory_structure(formatted)
    if structure_error is not None:
        label = (
            str(override)
            if override is not None
            else f"packaged {MEMORY_SASE_TEMPLATE_FILENAME}"
        )
        return None, f"{label}: {structure_error}"
    return formatted, None


def generated_sase_memory_relative_path() -> Path:
    """Return the generated ``sase/memory/sase.md`` root-relative path."""
    return CANONICAL_MEMORY_RELATIVE_ROOT / "sase.md"


def generated_glossary_memory_relative_path() -> Path:
    """Return the generated glossary note's root-relative path."""
    return CANONICAL_MEMORY_RELATIVE_ROOT / "glossary.md"


def _generated_artifacts_memory_relative_path() -> Path:
    return CANONICAL_MEMORY_RELATIVE_ROOT / "sase_artifacts.md"


def _generated_beads_memory_relative_path() -> Path:
    return CANONICAL_MEMORY_RELATIVE_ROOT / "sase_beads.md"


def _generated_sizes_memory_relative_path() -> Path:
    return CANONICAL_MEMORY_RELATIVE_ROOT / "sase_sizes.md"


_GENERATED_ARTIFACTS_MEMORY_SPEC = _GeneratedLongMemorySpec(
    template_filename=MEMORY_SASE_ARTIFACTS_TEMPLATE_FILENAME,
    relative_path=_generated_artifacts_memory_relative_path(),
    parent=AGENTS_PARENT,
    detail="generated SASE artifact memory",
)
_GENERATED_BEADS_MEMORY_SPEC = _GeneratedLongMemorySpec(
    template_filename=MEMORY_SASE_BEADS_TEMPLATE_FILENAME,
    relative_path=_generated_beads_memory_relative_path(),
    parent=AGENTS_PARENT,
    detail="generated SASE bead memory",
)
_GENERATED_SIZES_MEMORY_SPEC = _GeneratedLongMemorySpec(
    template_filename=MEMORY_SASE_SIZES_TEMPLATE_FILENAME,
    relative_path=_generated_sizes_memory_relative_path(),
    parent=_generated_beads_memory_relative_path().as_posix(),
    detail="generated SASE size memory",
)
_GENERATED_PROJECT_LONG_MEMORY_SPECS = (
    _GENERATED_ARTIFACTS_MEMORY_SPEC,
    _GENERATED_BEADS_MEMORY_SPEC,
    _GENERATED_SIZES_MEMORY_SPEC,
)


def render_generated_sase_memory_body(
    root: Path,
    entries: Iterable[LinkedRepoMemoryEntry],
    *,
    project_name: str | None = None,
) -> tuple[str | None, str | None]:
    """Render the stable ``sase/memory/sase.md`` body or return a blocker."""
    return _render_sase_memory(root, entries, project_name=project_name)


def generated_sase_memory_content(generated_sase_body: str) -> str:
    """Return ``sase/memory/sase.md`` with generated core-note frontmatter."""
    return apply_memory_frontmatter(
        generated_sase_body,
        note_type="core",
        parent=AGENTS_PARENT,
        priority=GENERATED_SASE_MEMORY_PRIORITY,
    )


def generated_memory_note_relative_paths(
    *, include_project_memory: bool
) -> tuple[Path, ...]:
    """Return the generated memory-note paths for one memory root.

    Shared notes are always included. Project-only notes
    (``task_types.md``, ``artifact_relations.md``, ``glossary.md``,
    ``sase_artifacts.md``, ``sase_beads.md``, and ``sase_sizes.md``) are added
    when *include_project_memory* is true; ``glossary.md`` is reserved for the
    generated note whether or not this project declares glossary entries,
    because ``sase memory init`` either regenerates that path or blocks on an
    unmarked note already sitting there. The path helpers feed this set so the
    two cannot drift.
    """
    paths = (generated_sase_memory_relative_path(),)
    if include_project_memory:
        return (
            *paths,
            generated_task_types_memory_relative_path(),
            generated_artifact_relations_memory_relative_path(),
            generated_glossary_memory_relative_path(),
            _generated_artifacts_memory_relative_path(),
            _generated_beads_memory_relative_path(),
            _generated_sizes_memory_relative_path(),
        )
    return paths


def _render_glossary_term_entry(term: str, display_aliases: tuple[str, ...]) -> str:
    escaped_term = md_escape(term)
    if not display_aliases:
        return escaped_term
    escaped_aliases = ", ".join(md_escape(alias) for alias in display_aliases)
    return f"{escaped_term} ({escaped_aliases})"


def render_generated_glossary_memory_body(
    glossary_terms: ProjectGlossaryTerms,
) -> tuple[str | None, str | None]:
    """Render the stable ``sase/memory/glossary.md`` body or return a blocker."""
    if not glossary_terms.terms:
        return None, None
    entries = "; ".join(
        _render_glossary_term_entry(term, display_aliases)
        for term, display_aliases in glossary_terms.terms
    )
    rendered, render_error = render_markdown_template(
        package=_MEMORY_TEMPLATE_PACKAGE,
        filename=f"templates/{MEMORY_SASE_GLOSSARY_TEMPLATE_FILENAME}",
        required_variables=_MEMORY_SASE_GLOSSARY_TEMPLATE_VARS,
        context={"glossary_term_entries": entries},
    )
    if render_error is not None or rendered is None:
        return (
            None,
            render_error or "failed to render sase/memory/glossary.md template",
        )
    formatted = format_generated_memory_markdown(rendered)
    structure_error = validate_short_memory_structure(formatted)
    if structure_error is not None:
        return (
            None,
            f"packaged {MEMORY_SASE_GLOSSARY_TEMPLATE_FILENAME}: {structure_error}",
        )
    return formatted, None


def generated_glossary_memory_content(generated_glossary_body: str) -> str:
    """Return ``sase/memory/glossary.md`` with generated core-note frontmatter."""
    return apply_memory_frontmatter(
        generated_glossary_body,
        note_type="core",
        parent=AGENTS_PARENT,
        extra={GENERATED_GLOSSARY_MARKER_KEY: GENERATED_GLOSSARY_MARKER_VALUE},
    )


def _render_generated_long_memory_content(
    *,
    template_filename: str,
    relative_path: Path,
    parent: str,
) -> tuple[str | None, str | None]:
    """Render a packaged generated reference memory note."""
    rendered, render_error = render_markdown_template(
        package=_MEMORY_TEMPLATE_PACKAGE,
        filename=f"templates/{template_filename}",
        required_variables=frozenset(),
        context={},
    )
    if render_error is not None or rendered is None:
        return (
            None,
            render_error or f"failed to render {relative_path.as_posix()} template",
        )
    formatted = format_generated_memory_markdown(rendered)
    note = parse_memory_note_text(
        formatted,
        relative_path,
    )
    if note.description is None:
        return (
            None,
            f"packaged {template_filename}: "
            "generated reference memory note must have a description",
        )
    canonical_parent = (
        AGENTS_PARENT
        if parent == AGENTS_PARENT
        else canonical_memory_reference(parent).as_posix()
    )
    return (
        apply_memory_frontmatter(
            formatted,
            note_type="reference",
            parent=canonical_parent,
            description=note.description,
        ),
        None,
    )


def _render_generated_project_long_memory_content(
    spec: _GeneratedLongMemorySpec,
) -> tuple[str | None, str | None]:
    """Render one generated project-only reference memory note."""
    return _render_generated_long_memory_content(
        template_filename=spec.template_filename,
        relative_path=spec.relative_path,
        parent=spec.parent,
    )


def render_generated_project_long_memory_contents() -> tuple[
    dict[str, str], str | None
]:
    """Render generated project-only reference memory notes keyed by relative path."""
    contents: dict[str, str] = {}
    for spec in _GENERATED_PROJECT_LONG_MEMORY_SPECS:
        content, error = _render_generated_project_long_memory_content(spec)
        if error is not None or content is None:
            return {}, error or f"failed to render {spec.relative_path.as_posix()}"
        contents[spec.relative_path.as_posix()] = content
    return contents, None


def generated_project_long_expected_files(
    root: Path,
    contents: Mapping[str, str],
) -> tuple[MemoryExpectedFile, ...]:
    """Return expected files for generated project-only reference memory notes."""
    expected: list[MemoryExpectedFile] = []
    for spec in _GENERATED_PROJECT_LONG_MEMORY_SPECS:
        generated_long_content = contents.get(spec.relative_path.as_posix())
        if generated_long_content is None:
            continue
        expected.append(
            MemoryExpectedFile(
                path=root / spec.relative_path,
                content=generated_long_content,
                detail=spec.detail,
            )
        )
    return tuple(expected)


def generated_short_notes(
    generated_sase_body: str,
    generated_artifact_relations_body: str | None = None,
    generated_glossary_body: str | None = None,
) -> dict[str, GeneratedShortMemoryNote]:
    """Return freshly generated core notes keyed by relative path.

    ``sase/memory/task_types.md`` is a generated memory web, not a plain note,
    so its body flows through ``_memory_web_root_plan``'s core-note-body
    overlay instead of this function.
    """
    notes = {
        generated_sase_memory_relative_path().as_posix(): GeneratedShortMemoryNote(
            body=generated_sase_body,
            priority=GENERATED_SASE_MEMORY_PRIORITY,
        ),
    }
    if generated_artifact_relations_body is not None:
        notes[generated_artifact_relations_memory_relative_path().as_posix()] = (
            GeneratedShortMemoryNote(generated_artifact_relations_body)
        )
    if generated_glossary_body is not None:
        notes[generated_glossary_memory_relative_path().as_posix()] = (
            GeneratedShortMemoryNote(generated_glossary_body)
        )
    return notes


def generated_long_notes(
    generated_contents: Mapping[str, str],
) -> dict[str, GeneratedLongMemoryNote]:
    """Return generated reference-note metadata keyed by relative path."""
    result: dict[str, GeneratedLongMemoryNote] = {}
    for relative_path, content in generated_contents.items():
        note = parse_memory_note_text(content, relative_path)
        if note.description is None:
            raise ValueError(
                f"generated reference memory note lacks a description: {relative_path}"
            )
        result[relative_path] = GeneratedLongMemoryNote(
            description=note.description,
            parent=note.parent,
        )
    return result
