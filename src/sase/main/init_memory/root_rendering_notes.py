"""Generated memory-note rendering helpers for memory root initialization."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

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
from .models import LinkedRepoMemoryEntry, MemoryExpectedFile
from .root_rendering_artifact_relations import (
    ARTIFACT_RELATION_REGISTRY_TEMPLATE_VARS,
    artifact_relation_registry_template_context,
)
from .root_rendering_task_types import generated_task_types_memory_relative_path

MEMORY_SASE_TEMPLATE_FILENAME = "memory-sase.template.md"
MEMORY_SASE_ARTIFACTS_TEMPLATE_FILENAME = "memory-sase-artifacts.template.md"
MEMORY_SASE_BEADS_TEMPLATE_FILENAME = "memory-sase-beads.template.md"
MEMORY_SASE_SIZES_TEMPLATE_FILENAME = "memory-sase-sizes.template.md"
_MEMORY_TEMPLATE_PACKAGE = "sase.main.init_memory"
_MEMORY_SASE_TEMPLATE_VARS = frozenset({"project_name", "linked_repo_entries"})
GENERATED_SASE_MEMORY_PRIORITY = 10


@dataclass(frozen=True)
class _GeneratedLongMemorySpec:
    template_filename: str
    relative_path: Path
    parent: str
    detail: str
    required_variables: frozenset[str] = frozenset()
    context: Callable[[], tuple[Mapping[str, object] | None, str | None]] | None = None


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
    required_variables=ARTIFACT_RELATION_REGISTRY_TEMPLATE_VARS,
    context=artifact_relation_registry_template_context,
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
    (``task_types.md``, ``sase_artifacts.md``, ``sase_beads.md``, and
    ``sase_sizes.md``) are added when *include_project_memory* is true.
    ``glossary.md`` is user-owned web descriptor content and is never reserved
    as a generated note.
    """
    paths = (generated_sase_memory_relative_path(),)
    if include_project_memory:
        return (
            *paths,
            generated_task_types_memory_relative_path(),
            _generated_artifacts_memory_relative_path(),
            _generated_beads_memory_relative_path(),
            _generated_sizes_memory_relative_path(),
        )
    return paths


def _render_generated_long_memory_content(
    *,
    template_filename: str,
    relative_path: Path,
    parent: str,
    required_variables: frozenset[str] = frozenset(),
    context: Callable[[], tuple[Mapping[str, object] | None, str | None]] | None = None,
) -> tuple[str | None, str | None]:
    """Render a packaged generated reference memory note."""
    render_context: Mapping[str, object] = {}
    if context is not None:
        context_values, context_error = context()
        if context_error is not None or context_values is None:
            return (
                None,
                context_error
                or f"failed to build context for {relative_path.as_posix()} template",
            )
        render_context = context_values
    rendered, render_error = render_markdown_template(
        package=_MEMORY_TEMPLATE_PACKAGE,
        filename=f"templates/{template_filename}",
        required_variables=required_variables,
        context=render_context,
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
        required_variables=spec.required_variables,
        context=spec.context,
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
) -> dict[str, GeneratedShortMemoryNote]:
    """Return freshly generated core notes keyed by relative path.

    ``sase/memory/task_types.md`` is a generated memory web, not a plain note,
    so its body flows through ``_memory_web_root_plan``'s core-note-body
    overlay instead of this function.
    """
    return {
        generated_sase_memory_relative_path().as_posix(): GeneratedShortMemoryNote(
            body=generated_sase_body,
            priority=GENERATED_SASE_MEMORY_PRIORITY,
        ),
    }


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
