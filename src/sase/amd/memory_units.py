"""Structured, side-effect-free memory units for one memory root.

This module is the single structured seam between the legacy ``AGENTS.md``
renderer and the instruction-bundle compiler: :func:`collect_memory_root_units`
reads one root and returns a frozen :class:`MemoryRootUnits` value, and
:func:`render_memory_root_units` turns those units back into the exact legacy
document bytes. The legacy ``_render_managed_agents`` path is rebuilt on these
two functions, so legacy output stays byte-identical while the compiler can
consume the same units without reimplementing discovery.

Collection performs no writes and reads no process-global state: the caller
passes ``root`` explicitly, and every discovery helper receives it (plus
``source_memory_root``) instead of falling back to ``Path.cwd()``. The one
convention the compiler must follow is the home-root choice — memory init
passes the chezmoi source checkout as ``source_memory_root`` for home roots,
while bundle compilation passes ``root=Path.home()`` with
``source_memory_root=None`` so the audited home lookup applies.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ._agents_doc import collect_long_memory_entries, parse_amd_agents_document
from ._chezmoi_template import unescape_chezmoi_literals
from ._headings import iter_headings
from ._shared import existing_agents_path, read_text
from ._template import render_agents_template
from .inline_memory import inline_memory_section
from sase.markdown_width import markdown_print_width
from sase.markdown_wrap import wrap_markdown
from sase.memory.notes import (
    AGENTS_PARENT,
    GeneratedLongMemoryNote,
    GeneratedShortMemoryNote,
    MemoryNote,
    collapse_description,
    discover_memory_notes,
    render_long_memory_entries,
)
from sase.memory.paths import CANONICAL_MEMORY_RELATIVE_ROOT
from sase.memory.web.discovery import discover_memory_webs

if TYPE_CHECKING:
    from sase.main.init_memory.models import LinkedRepoMemoryEntry

GENERATED_CONTRACT_RELATIVE_PATH = (
    CANONICAL_MEMORY_RELATIVE_ROOT / "sase.md"
).as_posix()

_CORE_MEMORY_INTRO = "The following memories contain core (always loaded) context:"
_LONG_MEMORY_INTRO = (
    "The below files contain detailed reference material. When working in "
    "their domain, you MUST use your `/sase_memory_read` skill to review "
    "their contents. Do not read canonical memory files directly."
)
_LONG_MEMORY_INTRO_FIRST_SENTENCE = _LONG_MEMORY_INTRO.split(".", 1)[0] + "."
_WEB_MEMORY_INTRO = (
    "Each memory web below is a keyed collection. Its descriptor is always "
    "loaded, but a strand's body is not: read strands on demand with your "
    "`/sase_memory_read` skill, for example `sase memory read glossary:stitch "
    '-r "<why>"`.'
)
_WEB_MEMORY_INTRO_FIRST_SENTENCE = _WEB_MEMORY_INTRO.split(".", 1)[0] + "."


@dataclass(frozen=True)
class ContractInputs:
    """Inputs to the generated ``sase.md`` contract note for one root."""

    project_name: str | None
    linked_entries: tuple[LinkedRepoMemoryEntry, ...]
    template_path: Path | None = None
    linked_entries_source: Path | None = None


@dataclass(frozen=True)
class _CoreMemoryUnit:
    """One ordered core note, inlined into Core Memory."""

    stem: str
    relative_path: str
    title: str | None
    text: str
    source_path: Path
    source_bytes: str
    generated_contract: bool
    priority: int


@dataclass(frozen=True)
class _ReferenceMemoryUnit:
    """One ordered top-level reference note for Reference Memory."""

    stem: str
    relative_path: str
    description: str
    used_legacy_fallback: bool
    entry_text: str
    source_path: Path
    source_bytes: str


@dataclass(frozen=True)
class _WebMemoryUnit:
    """One ordered memory web descriptor for Memory Webs."""

    stem: str
    relative_path: str
    title: str | None
    block: str
    descriptor_source: Path
    strand_files: tuple[Path, ...]
    priority: int


@dataclass(frozen=True)
class _MemoryIntroTexts:
    """Intro paragraphs preceding each rendered memory group."""

    core: str
    reference: str
    webs: str


@dataclass(frozen=True)
class MemoryRootUnits:
    """Structured, side-effect-free view of one root's memory inputs."""

    root: Path
    title: str | None
    contract_inputs: ContractInputs
    core: tuple[_CoreMemoryUnit, ...]
    references: tuple[_ReferenceMemoryUnit, ...]
    webs: tuple[_WebMemoryUnit, ...]
    intros: _MemoryIntroTexts


def _source_bytes(source_path: Path, *, fallback: str) -> str:
    text, error = read_text(source_path)
    if error is not None or text is None:
        return fallback
    return text


def _discover_notes_excluding(
    root: Path,
    *,
    source_memory_root: Path | None,
    excluded_note_paths: frozenset[str],
) -> tuple[MemoryNote, ...]:
    return tuple(
        note
        for note in discover_memory_notes(root, source_memory_root=source_memory_root)
        if note.relative_path not in excluded_note_paths
    )


def _short_memory_bodies(
    root: Path,
    generated_short_notes: Mapping[str, GeneratedShortMemoryNote],
    generated_long_notes: Mapping[str, GeneratedLongMemoryNote],
    *,
    source_memory_root: Path | None,
    excluded_note_paths: frozenset[str],
) -> dict[str, GeneratedShortMemoryNote]:
    generated_long_note_paths = frozenset(generated_long_notes or {})
    bodies: dict[str, GeneratedShortMemoryNote] = {
        note.relative_path: GeneratedShortMemoryNote(
            body=note.body,
            priority=note.priority,
        )
        for note in discover_memory_notes(root, source_memory_root=source_memory_root)
        if note.type == "core"
        and not note.is_web_descriptor
        and note.relative_path not in excluded_note_paths
        and note.relative_path not in generated_long_note_paths
    }
    bodies.update(generated_short_notes)
    return dict(
        sorted(
            bodies.items(),
            key=lambda item: (item[1].priority, item[0]),
        )
    )


def _web_memory_bodies(
    root: Path,
    generated_web_notes: Mapping[str, GeneratedShortMemoryNote],
    *,
    source_memory_root: Path | None,
    excluded_note_paths: frozenset[str],
) -> dict[str, GeneratedShortMemoryNote]:
    bodies: dict[str, GeneratedShortMemoryNote] = {
        note.relative_path: GeneratedShortMemoryNote(
            body=note.body,
            priority=note.priority,
        )
        for note in discover_memory_notes(root, source_memory_root=source_memory_root)
        if note.is_web_descriptor and note.relative_path not in excluded_note_paths
    }
    bodies.update(generated_web_notes)
    return dict(
        sorted(
            bodies.items(),
            key=lambda item: (item[1].priority, Path(item[0]).stem),
        )
    )


def _unit_title(body: str) -> str | None:
    """Return the text of the first H1 heading in *body*, fence-aware."""
    for level, line in iter_headings(body):
        if level == 1:
            return line.lstrip("#").strip()
    return None


def _existing_agents_long_descriptions(root: Path) -> dict[str, str]:
    """Return legacy reference descriptions keyed by note path for *root*."""
    agents_path = existing_agents_path(root)
    if agents_path is None:
        return {}
    text, error = read_text(agents_path)
    if error is not None or text is None:
        return {}
    text = unescape_chezmoi_literals(text)
    parsed = parse_amd_agents_document(text)
    if parsed.has_long_section:
        entries = parsed.long_memory_entries
    else:
        lines = text.splitlines()
        entries = collect_long_memory_entries(lines, 0, len(lines))
    return {entry.path: entry.description for entry in entries if entry.description}


def _first_body_paragraph_or_h1(body: str) -> str:
    h1 = ""
    paragraphs: list[list[str]] = []
    current: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if line.startswith("# ") and not h1:
            h1 = line[2:].strip()
            continue
        if not line:
            if current:
                paragraphs.append(current)
                current = []
            continue
        if line.startswith("#"):
            continue
        current.append(line)
    if current:
        paragraphs.append(current)
    if paragraphs:
        return " ".join(" ".join(paragraphs[0]).split())
    return " ".join(h1.split())


def _resolve_reference_description(
    root: Path,
    note: MemoryNote,
    *,
    existing_descriptions: Mapping[str, str],
) -> tuple[str, bool]:
    """Return the resolved description plus whether the legacy fallback fed it."""
    if note.description:
        return note.description, False
    existing = existing_descriptions.get(note.relative_path)
    if existing:
        return existing, True
    fallback = _first_body_paragraph_or_h1(note.body)
    if fallback:
        return fallback, False
    return (
        (root / note.path)
        .stem.replace("_", " ")
        .replace("-", " ")
        .strip()
        .capitalize(),
        False,
    )


def _long_memory_descriptions(
    root: Path,
    generated_long_notes: Mapping[str, GeneratedLongMemoryNote],
    *,
    source_memory_root: Path | None,
    excluded_note_paths: frozenset[str],
    existing_descriptions: Mapping[str, str],
) -> dict[str, str]:
    """Return resolved reference descriptions keyed by note path for *root*."""
    notes = _discover_notes_excluding(
        root,
        source_memory_root=source_memory_root,
        excluded_note_paths=excluded_note_paths,
    )
    descriptions = {
        note.relative_path: _resolve_reference_description(
            root, note, existing_descriptions=existing_descriptions
        )[0]
        for note in notes
        if note.type == "reference" and not note.is_web_descriptor
    }
    descriptions.update(
        {
            relative_path: generated.description
            for relative_path, generated in generated_long_notes.items()
        }
    )
    return descriptions


def _top_level_reference_notes(
    root: Path,
    generated_long_notes: Mapping[str, GeneratedLongMemoryNote],
    *,
    source_memory_root: Path | None,
    excluded_note_paths: frozenset[str],
) -> tuple[MemoryNote, ...]:
    notes_by_relative_path = {
        note.relative_path: note
        for note in _discover_notes_excluding(
            root,
            source_memory_root=source_memory_root,
            excluded_note_paths=excluded_note_paths,
        )
    }
    for relative_path, generated in (generated_long_notes or {}).items():
        existing = notes_by_relative_path.get(relative_path)
        notes_by_relative_path[relative_path] = MemoryNote(
            path=Path(relative_path),
            type="reference",
            parent=generated.parent,
            description=generated.description,
            body="" if existing is None else existing.body,
            frontmatter={},
            type_source="frontmatter",
            parent_source="frontmatter",
        )
    return tuple(
        sorted(
            (
                note
                for note in notes_by_relative_path.values()
                if note.type == "reference"
                and not note.is_web_descriptor
                and note.parent == AGENTS_PARENT
            ),
            key=lambda note: note.relative_path,
        )
    )


def _unnumbered_reference_entry(relative_path: str, description: str | None) -> str:
    """Render one reference entry without its positional list number."""
    collapsed = collapse_description(description)
    entry = (
        f"**`{relative_path}`** - {collapsed}"
        if collapsed
        else f"**`{relative_path}`**"
    )
    return wrap_markdown(entry, width=markdown_print_width())


def _strand_files_for_web(
    root: Path,
    relative_path: str,
    *,
    source_memory_root: Path | None,
    web_strand_files: Mapping[str, tuple[Path, ...]] | None,
) -> tuple[Path, ...]:
    """Return the strand files that fed the roster for one web descriptor."""
    if web_strand_files is not None and relative_path in web_strand_files:
        return tuple(web_strand_files[relative_path])
    try:
        discovery = discover_memory_webs(root, source_memory_root=source_memory_root)
    except Exception:
        discovery = None
    if discovery is not None:
        for web in discovery.webs:
            if web.relative_path == relative_path:
                return tuple(strand.path for strand in web.strands)
    strand_dir = (
        (source_memory_root or root)
        / CANONICAL_MEMORY_RELATIVE_ROOT
        / Path(relative_path).stem
    )
    try:
        if strand_dir.is_dir():
            return tuple(
                sorted(path for path in strand_dir.glob("*.md") if path.is_file())
            )
    except OSError:
        pass
    return ()


def collect_memory_root_units(
    root: Path,
    title: str | None,
    *,
    project_name: str | None = None,
    linked_entries: Iterable[LinkedRepoMemoryEntry] = (),
    contract_template_path: Path | None = None,
    linked_entries_source: Path | None = None,
    generated_short_notes: Mapping[str, GeneratedShortMemoryNote] | None = None,
    generated_long_notes: Mapping[str, GeneratedLongMemoryNote] | None = None,
    generated_web_notes: Mapping[str, GeneratedShortMemoryNote] | None = None,
    long_memory_descriptions: Mapping[str, str] | None = None,
    source_memory_root: Path | None = None,
    excluded_note_paths: frozenset[str] = frozenset(),
    web_strand_files: Mapping[str, tuple[Path, ...]] | None = None,
) -> MemoryRootUnits:
    """Collect the structured memory units for *root* without side effects.

    *root* is required: collection never falls back to ``Path.cwd()``. Pass
    ``source_memory_root`` for the chezmoi-source home checkout during memory
    init; pass ``None`` with ``root=Path.home()`` when compiling bundles.
    *long_memory_descriptions* may carry precomputed reference descriptions
    (memory init computes them for blocker checks first); when omitted they
    are resolved here, including the legacy ``AGENTS.md`` description fallback.
    """
    generated_short_notes = generated_short_notes or {}
    generated_long_notes = generated_long_notes or {}
    generated_web_notes = generated_web_notes or {}

    existing_descriptions = _existing_agents_long_descriptions(root)
    descriptions = (
        dict(long_memory_descriptions)
        if long_memory_descriptions is not None
        else _long_memory_descriptions(
            root,
            generated_long_notes,
            source_memory_root=source_memory_root,
            excluded_note_paths=excluded_note_paths,
            existing_descriptions=existing_descriptions,
        )
    )

    short_bodies = _short_memory_bodies(
        root,
        generated_short_notes,
        generated_long_notes,
        source_memory_root=source_memory_root,
        excluded_note_paths=excluded_note_paths,
    )
    web_bodies = _web_memory_bodies(
        root,
        generated_web_notes,
        source_memory_root=source_memory_root,
        excluded_note_paths=excluded_note_paths,
    )
    top_level_notes = _top_level_reference_notes(
        root,
        generated_long_notes,
        source_memory_root=source_memory_root,
        excluded_note_paths=excluded_note_paths,
    )

    disk_notes = {
        note.relative_path: note
        for note in _discover_notes_excluding(
            root,
            source_memory_root=source_memory_root,
            excluded_note_paths=excluded_note_paths,
        )
    }

    core: list[_CoreMemoryUnit] = []
    for relative_path, short_note in short_bodies.items():
        disk_note = disk_notes.get(relative_path)
        if disk_note is not None:
            source_path = root / disk_note.source_relative_path
        else:
            source_path = root / relative_path
        core.append(
            _CoreMemoryUnit(
                stem=Path(relative_path).stem,
                relative_path=relative_path,
                title=_unit_title(short_note.body),
                text=inline_memory_section(relative_path, short_note.body),
                source_path=source_path,
                source_bytes=_source_bytes(source_path, fallback=short_note.body),
                generated_contract=(
                    relative_path == GENERATED_CONTRACT_RELATIVE_PATH
                    and relative_path in generated_short_notes
                ),
                priority=short_note.priority,
            )
        )

    references: list[_ReferenceMemoryUnit] = []
    for ref_note in top_level_notes:
        # A falsy entry is treated as missing, mirroring the legacy
        # `descriptions.get(...) or _long_memory_description(...)` fallback.
        description = descriptions.get(ref_note.relative_path) or None
        if description is None:
            resolved, used_fallback = _resolve_reference_description(
                root, ref_note, existing_descriptions=existing_descriptions
            )
        else:
            resolved = description
            used_fallback = not ref_note.description and bool(
                existing_descriptions.get(ref_note.relative_path)
            )
        source_path = root / ref_note.source_relative_path
        references.append(
            _ReferenceMemoryUnit(
                stem=Path(ref_note.relative_path).stem,
                relative_path=ref_note.relative_path,
                description=resolved,
                used_legacy_fallback=used_fallback,
                entry_text=_unnumbered_reference_entry(
                    ref_note.relative_path, resolved
                ),
                source_path=source_path,
                source_bytes=_source_bytes(source_path, fallback=ref_note.body),
            )
        )

    webs: list[_WebMemoryUnit] = []
    for relative_path, web_note in web_bodies.items():
        disk_note = disk_notes.get(relative_path)
        if disk_note is not None:
            descriptor_source = root / disk_note.source_relative_path
        else:
            descriptor_source = root / relative_path
        webs.append(
            _WebMemoryUnit(
                stem=Path(relative_path).stem,
                relative_path=relative_path,
                title=_unit_title(web_note.body),
                block=inline_memory_section(relative_path, web_note.body),
                descriptor_source=descriptor_source,
                strand_files=_strand_files_for_web(
                    root,
                    relative_path,
                    source_memory_root=source_memory_root,
                    web_strand_files=web_strand_files,
                ),
                priority=web_note.priority,
            )
        )

    return MemoryRootUnits(
        root=root,
        title=title,
        contract_inputs=ContractInputs(
            project_name=project_name,
            linked_entries=tuple(linked_entries),
            template_path=contract_template_path,
            linked_entries_source=linked_entries_source,
        ),
        core=tuple(core),
        references=tuple(references),
        webs=tuple(webs),
        intros=_MemoryIntroTexts(
            core=_CORE_MEMORY_INTRO,
            reference=_LONG_MEMORY_INTRO,
            webs=_WEB_MEMORY_INTRO,
        ),
    )


def render_memory_root_units(
    units: MemoryRootUnits,
) -> tuple[str | None, str | None]:
    """Render the legacy managed ``AGENTS.md`` document from *units*.

    The composition mirrors the pre-units renderer exactly: core sections and
    web blocks joined the same way, reference entries numbered through the
    same ``render_long_memory_entries`` call, the same template render, and
    the same structural validations with identical blocker messages.
    """
    core_sections = "\n\n".join(unit.text.rstrip("\n") for unit in units.core)
    web_block = "\n\n".join(unit.block.rstrip("\n") for unit in units.webs)
    web_sections = (
        f"## Memory Webs\n\n{units.intros.webs}\n\n{web_block}" if web_block else ""
    )

    rendered_long_notes = [
        MemoryNote(
            path=Path(unit.relative_path),
            type="reference",
            parent=AGENTS_PARENT,
            description=unit.description,
            body="",
            frontmatter={},
            type_source="frontmatter",
            parent_source="frontmatter",
        )
        for unit in units.references
    ]
    long_entries = render_long_memory_entries(rendered_long_notes)
    reference_entries = (
        "" if not long_entries else f"{units.intros.reference}\n\n{long_entries}"
    )

    if units.title is None:
        return None, "memory units have no title; cannot render managed AGENTS.md"
    rendered, render_error = render_agents_template(
        units.root,
        title=units.title,
        core_sections=core_sections,
        web_sections=web_sections,
        reference_entries=reference_entries,
    )
    if render_error is not None or rendered is None:
        return None, render_error or "failed to render AGENTS template"

    parsed = parse_amd_agents_document(rendered)
    if not parsed.has_short_section:
        return (
            None,
            "rendered AGENTS template is missing structural anchor `## Core Memory`",
        )
    if not parsed.has_long_section:
        return (
            None,
            "rendered AGENTS template is missing structural anchor "
            "`## Reference Memory`",
        )
    expected_short_paths = tuple(unit.relative_path for unit in units.core)
    if parsed.short_memory_paths != expected_short_paths:
        return (
            None,
            "rendered AGENTS template has unexpected Core Memory paths: "
            f"expected {expected_short_paths!r}, found {parsed.short_memory_paths!r}",
        )
    expected_web_paths = tuple(unit.relative_path for unit in units.webs)
    if expected_web_paths:
        if not parsed.has_web_section:
            return (
                None,
                "rendered AGENTS template is missing structural anchor "
                "`## Memory Webs`",
            )
        if parsed.web_memory_paths != expected_web_paths:
            return (
                None,
                "rendered AGENTS template has unexpected Memory Webs paths: "
                f"expected {expected_web_paths!r}, found {parsed.web_memory_paths!r}",
            )
        if _WEB_MEMORY_INTRO_FIRST_SENTENCE not in rendered:
            return (
                None,
                "rendered AGENTS template is missing the Memory Webs "
                "instruction paragraph",
            )
    elif parsed.has_web_section:
        return (
            None,
            "rendered AGENTS template has unexpected Memory Webs section",
        )
    expected_long_paths = tuple(unit.relative_path for unit in units.references)
    parsed_long_paths = tuple(entry.path for entry in parsed.long_memory_entries)
    if parsed_long_paths != expected_long_paths:
        return (
            None,
            "rendered AGENTS template has unexpected Reference Memory paths: "
            f"expected {expected_long_paths!r}, found {parsed_long_paths!r}",
        )
    if units.references and _LONG_MEMORY_INTRO_FIRST_SENTENCE not in rendered:
        return (
            None,
            "rendered AGENTS template is missing the Reference Memory "
            "instruction paragraph",
        )
    return rendered, None


__all__ = [
    "ContractInputs",
    "GENERATED_CONTRACT_RELATIVE_PATH",
    "MemoryRootUnits",
    "collect_memory_root_units",
    "render_memory_root_units",
]
