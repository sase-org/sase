"""Migration engine for config-backed glossary memory webs."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass, replace
from importlib import resources
import os
from pathlib import Path
import stat
import tempfile
from typing import Any

from sase.config._edit_yaml import unset_key
from sase.config._edit_yaml_io import dump_yaml, make_yaml
from sase.config.core import clear_config_cache
from sase.content_layout import (
    LayoutCollisionError,
    discover_project_root,
    resolve_project_config_read_path,
)
from sase.core.glossary_facade import (
    GlossaryDiagnostic,
    GlossaryInputEntry,
    build_glossary_catalog,
    validate_glossary_entries,
)
from sase.glossary.resolution import normalize_glossary_reference
from sase.glossary_config import (
    GLOSSARY_CONFIG_KEY,
    MEMORY_CONFIG_KEY,
    resolve_glossary_config,
)
from sase.main.init_memory.glossary import ProjectGlossaryTerms
from sase.main.init_memory.root_rendering_notes import (
    render_generated_glossary_memory_body,
)
from sase.memory.cli_common import MemoryCliProjectError, resolve_memory_cli_project
from sase.memory.paths import memory_write_root
from sase.memory.web.catalog import GLOSSARY_WEB_SLUG, find_memory_web
from sase.memory.web.frontmatter import parse_memory_strand, parse_web_descriptor
from sase.memory.web.models import MemoryStrand, MemoryWebDiscovery
from sase.memory.web.roster import (
    END_MARKER,
    START_MARKER,
    render_web_descriptor_with_roster,
)
from sase.memory.web.validation import validate_memory_webs
from sase.xprompt._glossary_catalog_config import (
    load_round_trip_mapping,
    parse_glossary_entries,
    read_config_lines,
)


class MemoryWebMigrationError(RuntimeError):
    """Raised when a memory-web migration cannot be applied."""


@dataclass(frozen=True, slots=True)
class _MemoryWebMigrationReport:
    """Human-facing report for a planned or applied memory-web migration."""

    web: str
    strand_count: int
    strand_paths: tuple[Path, ...]
    descriptor_path: Path
    config_path: Path


@dataclass(frozen=True, slots=True)
class _MigrationPlan:
    report: _MemoryWebMigrationReport
    descriptor_text: str
    descriptor_expected: bytes | None
    config_text: str
    config_expected: bytes | None
    strand_texts: tuple[tuple[Path, str], ...]


def migrate_memory_web(
    web: str,
    *,
    project_ref: str | None = None,
    dry_run: bool = False,
) -> _MemoryWebMigrationReport:
    """Migrate a supported config-backed memory web and return its report."""

    if web != GLOSSARY_WEB_SLUG:
        raise MemoryWebMigrationError(
            "only the config glossary can be migrated in this release"
        )

    plan = _plan_glossary_migration(project_ref)
    if dry_run:
        return plan.report

    for path, text in plan.strand_texts:
        _write_text_atomically(path, text, None)
    _write_text_atomically(
        plan.report.descriptor_path,
        plan.descriptor_text,
        plan.descriptor_expected,
    )
    _write_text_atomically(
        plan.report.config_path,
        plan.config_text,
        plan.config_expected,
        clear_cache=True,
    )
    return plan.report


def render_migration_report(report: _MemoryWebMigrationReport) -> str:
    """Return the stable CLI report shared by dry-run and write mode."""

    lines = [f"migrate {report.web}: {report.strand_count} strands"]
    lines.extend(f"write: {path}" for path in report.strand_paths)
    lines.append(f"write: {report.descriptor_path}")
    lines.append(f"config: {report.config_path} (remove memory.glossary)")
    lines.append("follow-up: run `sase memory init`")
    return "\n".join(lines) + "\n"


def _plan_glossary_migration(project_ref: str | None) -> _MigrationPlan:
    root = _resolve_project_root(project_ref)
    config_path = _resolve_config_path(root)
    config_expected, config_text = _read_config_text(config_path)
    loaded, load_errors = load_round_trip_mapping(config_path)
    if load_errors:
        raise MemoryWebMigrationError("; ".join(load_errors))
    if not isinstance(loaded, Mapping):
        raise MemoryWebMigrationError(f"{config_path}: expected a YAML mapping")

    resolution = resolve_glossary_config(loaded)
    if resolution.error is not None:
        raise MemoryWebMigrationError(f"{config_path}: {resolution.error}")
    if not resolution.declared or resolution.node is None:
        raise MemoryWebMigrationError("nothing to migrate: memory.glossary is absent")

    memory_root = memory_write_root(root)
    descriptor_path = memory_root / f"{GLOSSARY_WEB_SLUG}.md"
    strand_dir = memory_root / GLOSSARY_WEB_SLUG
    descriptor_expected = _read_optional_bytes(descriptor_path)

    _refuse_existing_glossary_web(root, descriptor_path, strand_dir)

    entries = _load_glossary_entries(config_path, resolution)
    if not entries:
        raise MemoryWebMigrationError(
            "nothing to migrate: memory.glossary has no terms"
        )

    strand_texts = _strand_texts_for_entries(
        root=root,
        memory_root=memory_root,
        entries=entries,
    )
    strands = _parse_planned_strands(root, memory_root, strand_texts)
    descriptor_text = _render_descriptor(
        root=root,
        memory_root=memory_root,
        descriptor_path=descriptor_path,
        strands=strands,
    )
    _validate_planned_web(root, memory_root, descriptor_path, descriptor_text, strands)
    _assert_roster_parity(descriptor_text, entries)
    config_without_glossary = _remove_config_glossary(config_text, resolution.key_path)

    return _MigrationPlan(
        report=_MemoryWebMigrationReport(
            web=GLOSSARY_WEB_SLUG,
            strand_count=len(strand_texts),
            strand_paths=tuple(path for path, _text in strand_texts),
            descriptor_path=descriptor_path,
            config_path=config_path,
        ),
        descriptor_text=descriptor_text,
        descriptor_expected=descriptor_expected,
        config_text=config_without_glossary,
        config_expected=config_expected,
        strand_texts=strand_texts,
    )


def _resolve_project_root(project_ref: str | None) -> Path:
    if project_ref:
        try:
            resolved = resolve_memory_cli_project(project_ref)
        except MemoryCliProjectError as exc:
            raise MemoryWebMigrationError(str(exc)) from exc
        if resolved is None:  # pragma: no cover - guarded by project_ref
            raise MemoryWebMigrationError(
                f"project ref {project_ref!r} did not resolve to a workspace"
            )
        return resolved.project_root.resolve(strict=False)

    cwd = Path.cwd()
    return (discover_project_root(cwd) or cwd).resolve(strict=False)


def _resolve_config_path(root: Path) -> Path:
    try:
        config_path = resolve_project_config_read_path(root)
    except LayoutCollisionError as exc:
        raise MemoryWebMigrationError(str(exc)) from exc
    if config_path is None or not config_path.is_file():
        raise MemoryWebMigrationError("nothing to migrate: memory.glossary is absent")
    return config_path


def _read_config_text(path: Path) -> tuple[bytes, str]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise MemoryWebMigrationError(f"{path}: failed to read config: {exc}") from exc
    try:
        return data, data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MemoryWebMigrationError(f"{path}: config is not valid UTF-8") from exc


def _refuse_existing_glossary_web(
    root: Path,
    descriptor_path: Path,
    strand_dir: Path,
) -> None:
    existing_web = find_memory_web(root, GLOSSARY_WEB_SLUG)
    if existing_web is not None:
        raise MemoryWebMigrationError(
            f"{existing_web.path}: glossary memory web already exists; "
            "remove memory.glossary manually"
        )

    if descriptor_path.exists():
        descriptor, descriptor_error = parse_web_descriptor(
            root=root,
            memory_root=descriptor_path.parent,
            path=descriptor_path,
        )
        if descriptor_error is not None:
            raise MemoryWebMigrationError(descriptor_error)
        if descriptor is not None:
            raise MemoryWebMigrationError(
                f"{descriptor_path}: glossary memory web already exists; "
                "remove memory.glossary manually"
            )

    if strand_dir.is_dir():
        strands = sorted(
            path
            for path in strand_dir.iterdir()
            if path.is_file() and path.suffix == ".md"
        )
        if strands:
            raise MemoryWebMigrationError(
                f"{strand_dir}: glossary strands already exist; migration is one-shot"
            )


def _load_glossary_entries(
    config_path: Path,
    resolution: Any,
) -> tuple[GlossaryInputEntry, ...]:
    lines = read_config_lines(config_path)
    entries, shape_errors = parse_glossary_entries(
        config_path,
        resolution.node,
        lines,
        config_key_path=resolution.key_path,
        display_path=resolution.display_path,
    )
    if shape_errors:
        raise MemoryWebMigrationError("; ".join(shape_errors))

    try:
        diagnostics = validate_glossary_entries(entries)
    except (AttributeError, ImportError, ValueError, RuntimeError) as exc:
        raise MemoryWebMigrationError(
            f"{config_path}: failed to validate glossary: {exc}"
        ) from exc
    if diagnostics:
        rendered = "; ".join(
            _format_diagnostic(config_path, diagnostic, resolution.display_path)
            for diagnostic in diagnostics
        )
        raise MemoryWebMigrationError(rendered)

    return tuple(entries)


def _format_diagnostic(
    config_path: Path,
    diagnostic: GlossaryDiagnostic,
    display_path: str,
) -> str:
    path = diagnostic.path or display_path
    if path == GLOSSARY_CONFIG_KEY:
        path = display_path
    elif path.startswith(f"{GLOSSARY_CONFIG_KEY}."):
        path = f"{display_path}{path.removeprefix(GLOSSARY_CONFIG_KEY)}"
    return f"{config_path}: {path}: {diagnostic.code}: {diagnostic.message}"


def _strand_texts_for_entries(
    *,
    root: Path,
    memory_root: Path,
    entries: Sequence[GlossaryInputEntry],
) -> tuple[tuple[Path, str], ...]:
    paths_by_slug: dict[str, str] = {}
    planned: list[tuple[Path, str]] = []
    for entry in entries:
        slug = _term_slug(entry.term)
        previous = paths_by_slug.get(slug)
        if previous is not None:
            raise MemoryWebMigrationError(
                f"glossary terms {previous!r} and {entry.term!r} collide on "
                f"strand slug {slug!r}"
            )
        paths_by_slug[slug] = entry.term
        path = memory_root / GLOSSARY_WEB_SLUG / f"{slug}.md"
        planned.append((path, _strand_text(entry)))
    return tuple(planned)


def _term_slug(term: str) -> str:
    normalized = normalize_glossary_reference(term)
    slug = normalized.replace(" ", "-")
    if not slug:
        raise MemoryWebMigrationError(f"glossary term {term!r} has no usable slug")
    return slug


def _strand_text(entry: GlossaryInputEntry) -> str:
    from ruamel.yaml.comments import CommentedMap

    frontmatter = CommentedMap()
    frontmatter["keyword"] = entry.term
    if entry.aliases:
        frontmatter["aliases"] = list(entry.aliases)
    return (
        "---\n"
        f"{dump_yaml(make_yaml(), frontmatter)}"
        "---\n\n"
        f"{entry.definition.rstrip()}\n"
    )


def _parse_planned_strands(
    root: Path,
    memory_root: Path,
    strand_texts: Sequence[tuple[Path, str]],
) -> tuple[MemoryStrand, ...]:
    strands: list[MemoryStrand] = []
    for path, text in strand_texts:
        strand, error = parse_memory_strand(
            root=root,
            memory_root=memory_root,
            web_slug=GLOSSARY_WEB_SLUG,
            path=path,
            text=text,
        )
        if error is not None or strand is None:
            raise MemoryWebMigrationError(error or f"{path}: failed to parse strand")
        strands.append(strand)
    return tuple(strands)


def _render_descriptor(
    *,
    root: Path,
    memory_root: Path,
    descriptor_path: Path,
    strands: tuple[MemoryStrand, ...],
) -> str:
    descriptor, error = parse_web_descriptor(
        root=root,
        memory_root=memory_root,
        path=descriptor_path,
        text=_descriptor_seed_text(),
        source="generated",
    )
    if error is not None or descriptor is None:
        raise MemoryWebMigrationError(
            error or f"{descriptor_path}: failed to build glossary descriptor"
        )
    descriptor = replace(descriptor, strands=strands)
    content, render_error = render_web_descriptor_with_roster(descriptor)
    if render_error is not None or content is None:
        raise MemoryWebMigrationError(
            render_error or f"{descriptor_path}: failed to render glossary descriptor"
        )
    return content


def _descriptor_seed_text() -> str:
    return (
        "---\n"
        "type: core\n"
        "web: true\n"
        "roster: inline\n"
        "roster_label: GLOSSARY TERMS\n"
        "strand_noun: term\n"
        "closure: mentions\n"
        "---\n\n"
        f"{_descriptor_preamble()}\n"
    )


def _descriptor_preamble() -> str:
    template = (
        resources.files("sase.main.init_memory")
        .joinpath("templates/memory-sase-glossary.template.md")
        .read_text(encoding="utf-8")
    )
    preamble = template.split("**GLOSSARY TERMS:**", 1)[0]
    return preamble.replace(
        "sase glossary read <term>",
        "sase memory read glossary:<term>",
    ).rstrip()


def _validate_planned_web(
    root: Path,
    memory_root: Path,
    descriptor_path: Path,
    descriptor_text: str,
    strands: tuple[MemoryStrand, ...],
) -> None:
    web, parse_error = parse_web_descriptor(
        root=root,
        memory_root=memory_root,
        path=descriptor_path,
        text=descriptor_text,
        source="generated",
    )
    if parse_error is not None or web is None:
        raise MemoryWebMigrationError(
            parse_error or f"{descriptor_path}: failed to parse planned descriptor"
        )
    web = replace(web, strands=strands)
    report = validate_memory_webs(
        MemoryWebDiscovery(root=root, memory_root=memory_root, webs=(web,))
    )
    if report.blockers:
        raise MemoryWebMigrationError("; ".join(report.blockers))


def _assert_roster_parity(
    descriptor_text: str,
    entries: Sequence[GlossaryInputEntry],
) -> None:
    try:
        catalog = build_glossary_catalog(entries)
    except (AttributeError, ImportError, ValueError, RuntimeError) as exc:
        raise MemoryWebMigrationError(
            f"failed to build glossary roster: {exc}"
        ) from exc
    generated_body, render_error = render_generated_glossary_memory_body(
        ProjectGlossaryTerms(
            terms=tuple(
                (entry.term, entry.display_aliases) for entry in catalog.entries
            )
        )
    )
    if render_error is not None or generated_body is None:
        raise MemoryWebMigrationError(
            render_error or "failed to render generated glossary roster"
        )

    if _managed_roster_payload(descriptor_text) != _generated_roster_payload(
        generated_body
    ):
        raise MemoryWebMigrationError(
            "planned glossary roster does not match the generated glossary note"
        )


def _managed_roster_payload(descriptor_text: str) -> str:
    start = descriptor_text.find(START_MARKER)
    end = descriptor_text.find(END_MARKER, start)
    if start < 0 or end < 0:
        raise MemoryWebMigrationError(
            "planned glossary descriptor has no roster region"
        )
    start += len(START_MARKER)
    return descriptor_text[start:end].strip()


def _generated_roster_payload(generated_body: str) -> str:
    marker = "**GLOSSARY TERMS:**"
    start = generated_body.find(marker)
    if start < 0:
        raise MemoryWebMigrationError("generated glossary body has no roster line")
    return generated_body[start:].strip()


def _remove_config_glossary(text: str, key_path: tuple[str, ...]) -> str:
    updated = unset_key(text, key_path)
    data = _load_root_mapping(updated)
    if not isinstance(data, MutableMapping):
        return updated
    memory = data.get(MEMORY_CONFIG_KEY)
    if isinstance(memory, MutableMapping) and not memory:
        updated = unset_key(updated, (MEMORY_CONFIG_KEY,))
    return updated


def _read_optional_bytes(path: Path) -> bytes | None:
    if not path.is_file():
        return None
    return path.read_bytes()


def _load_root_mapping(text: str) -> MutableMapping[Any, Any] | None:
    try:
        data = make_yaml().load(text) if text.strip() else {}
    except Exception:
        return None
    if not isinstance(data, MutableMapping):
        return None
    return data


def _write_text_atomically(
    path: Path,
    new_text: str,
    expected_bytes: bytes | None,
    *,
    clear_cache: bool = False,
) -> None:
    current = _read_optional_bytes(path)
    if current != expected_bytes:
        raise MemoryWebMigrationError(f"{path}: changed after migration preview")
    created = current is None
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    replaced = False
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as stream:
            temp_path = Path(stream.name)
            if not created:
                mode = stat.S_IMODE(path.stat().st_mode)
                os.fchmod(stream.fileno(), mode)
            stream.write(new_text.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
        replaced = True
    finally:
        if not replaced and temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
    _fsync_directory(path.parent)
    if clear_cache:
        clear_config_cache()


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


__all__ = [
    "MemoryWebMigrationError",
    "migrate_memory_web",
    "render_migration_report",
]
