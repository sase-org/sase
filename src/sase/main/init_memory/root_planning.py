"""Planning helpers for memory root initialization."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from sase.amd._shared import ProviderShimPlan, provider_shim_plan
from sase.amd.init import (
    AmdMemorySyncPlan,
    plan_amd_memory_sync,
    plan_minimal_agents_sync,
)
from sase.memory.notes import GeneratedLongMemoryNote, GeneratedShortMemoryNote
from sase.memory.paths import CANONICAL_MEMORY_RELATIVE_ROOT
from sase.memory.web import (
    discover_memory_webs,
    render_web_body_with_roster,
    render_web_descriptor_with_roster,
    strip_managed_roster_markers,
    validate_memory_webs,
)

from .inventory import memory_parent_blockers, unreferenced_memory_files
from .models import (
    LinkedRepoMemoryEntry,
    MemoryExpectedFile,
    MemoryFileChange,
    MemoryRootPlan,
)
from .root_migration import memory_migration_plan
from .root_planning_files import (
    agent_doc_shim_plans,
    compare_expected_memory_files,
    final_agents_content,
    merge_expected_files,
    provider_shim_changes,
    provider_shim_plan_blockers,
    provider_shim_plan_changes,
    validation_overlay_for_expected_files,
)
from .root_rendering import (
    generated_long_notes,
    generated_short_notes,
    render_generated_project_long_memory_contents,
    render_generated_sase_memory_body,
    render_expected_memory_files,
)
from .root_rendering_artifact_relations import (
    ARTIFACT_RELATIONS_MEMORY_RELATIVE_PATH,
    is_generated_artifact_relations_memory_content,
)
from .root_rendering_task_types import (
    TASK_TYPES_WEB_SLUG,
    build_generated_task_types_web,
    current_agent_creatable_task_type_slugs,
    generated_task_types_memory_relative_path,
    is_generated_task_type_strand_content,
    is_generated_task_types_memory_content,
)


@dataclass(frozen=True)
class _MemoryRootContext:
    amd_sync: AmdMemorySyncPlan | None
    expected_files: tuple[MemoryExpectedFile, ...]
    shim_plan: ProviderShimPlan
    additional_shim_plans: tuple[ProviderShimPlan, ...]
    memory_delete_paths: tuple[Path, ...] = ()
    retired_note_paths: tuple[Path, ...] = ()
    source_memory_root: Path | None = None
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class _MemoryWebRootPlan:
    expected_files: tuple[MemoryExpectedFile, ...] = ()
    note_overlay: Mapping[Path, str] | None = None
    core_note_bodies: Mapping[str, GeneratedShortMemoryNote] | None = None
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def _retired_note_paths(
    root: Path, *, include_project_memory: bool
) -> tuple[Path, ...]:
    """Return generated project memory notes this root no longer manages.

    A root that stopped managing project-only notes (currently: every root except a
    SASE-managed project) still deletes previously generated copies so it converges in a
    single ``sase memory init`` pass. Only a file that is byte-identical to the current
    packaged render is considered SASE-owned; a human-edited copy is left alone and
    keeps behaving as an ordinary reference note.
    """
    if include_project_memory:
        return ()
    generated_contents, render_error = render_generated_project_long_memory_contents()
    if render_error is not None:
        return ()
    retired: list[Path] = []
    for relative_path, generated_content in generated_contents.items():
        path = root / relative_path
        if not path.exists():
            continue
        try:
            current = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if current == generated_content:
            retired.append(path)
    return tuple(retired)


def _retired_task_types_note_path(
    root: Path, *, include_project_memory: bool
) -> tuple[Path, ...]:
    """Return a generated task-type memory note this root no longer manages.

    When *include_project_memory* is true the path is generated, not retired.
    Otherwise a leftover whose body matches the generated heading signature is
    deleted; a hand-authored note at the same path is left alone.
    """
    if include_project_memory:
        return ()
    path = root / generated_task_types_memory_relative_path()
    if not path.exists():
        return ()
    try:
        current = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ()
    if not is_generated_task_types_memory_content(current):
        return ()
    return (path,)


def _retired_artifact_relations_note_path(root: Path) -> tuple[Path, ...]:
    """Return the retired generated artifact-relations note, if present."""
    path = root / ARTIFACT_RELATIONS_MEMORY_RELATIVE_PATH
    if not path.exists():
        return ()
    try:
        current = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ()
    if not is_generated_artifact_relations_memory_content(current):
        return ()
    return (path,)


def _retired_task_types_strand_paths(
    root: Path, *, include_project_memory: bool
) -> tuple[Path, ...]:
    """Return generated task-type strand files this root no longer manages.

    When *include_project_memory* is true, only a strand whose slug fell out
    of the committed, agent-creatable catalog retires; the rest keep
    regenerating through the web's expected files. Otherwise every strand
    matching the generated signature retires, mirroring
    ``_retired_task_types_note_path``. A hand-edited file at either path is
    left alone.
    """
    strand_dir = root / CANONICAL_MEMORY_RELATIVE_ROOT / TASK_TYPES_WEB_SLUG
    if not strand_dir.exists() or not strand_dir.is_dir():
        return ()
    current_slugs = (
        current_agent_creatable_task_type_slugs()
        if include_project_memory
        else frozenset()
    )
    retired: list[Path] = []
    for path in sorted(strand_dir.glob("*.md")):
        slug = path.stem
        if include_project_memory and slug in current_slugs:
            continue
        try:
            current = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not is_generated_task_type_strand_content(slug, current):
            continue
        retired.append(path)
    return tuple(retired)


def _amd_sync_plan(
    root: Path,
    *,
    enable_amd: bool,
    derive_project_title: bool,
    generated_short_notes: dict[str, GeneratedShortMemoryNote],
    generated_long_notes: dict[str, GeneratedLongMemoryNote],
    source_memory_root: Path,
    excluded_note_paths: frozenset[str] = frozenset(),
) -> AmdMemorySyncPlan | None:
    if not enable_amd:
        return plan_minimal_agents_sync(
            root,
            generated_short_notes=generated_short_notes,
        )
    return plan_amd_memory_sync(
        root,
        derive_project_title=derive_project_title,
        generated_short_notes=generated_short_notes,
        generated_long_notes=generated_long_notes,
        source_memory_root=source_memory_root,
        excluded_note_paths=excluded_note_paths,
    )


def _memory_web_root_plan(
    root: Path,
    *,
    source_memory_root: Path,
    include_project_memory: bool,
) -> _MemoryWebRootPlan:
    file_discovery = discover_memory_webs(root, source_memory_root=source_memory_root)
    webs = tuple(web for web in file_discovery.webs if web.slug != TASK_TYPES_WEB_SLUG)
    if include_project_memory:
        generated_web, generated_error = build_generated_task_types_web(root)
        if generated_error is not None or generated_web is None:
            return _MemoryWebRootPlan(
                blockers=(
                    generated_error
                    or "failed to render the generated task_types memory web",
                ),
            )
        webs = (*webs, generated_web)
    discovery = replace(file_discovery, webs=webs)

    validation = validate_memory_webs(discovery)
    if validation.blockers:
        return _MemoryWebRootPlan(
            blockers=validation.blockers,
            warnings=validation.warnings,
        )

    expected: list[MemoryExpectedFile] = []
    note_overlay: dict[Path, str] = {}
    core_note_bodies: dict[str, GeneratedShortMemoryNote] = {}
    blockers: list[str] = []
    for web in discovery.webs:
        body, body_error = render_web_body_with_roster(web)
        content, content_error = render_web_descriptor_with_roster(web)
        error = body_error or content_error
        if error is not None or body is None or content is None:
            blockers.append(f"{web.path}: {error or 'failed to render strand roster'}")
            continue
        note_overlay[web.path] = content
        core_note_bodies[web.relative_path] = GeneratedShortMemoryNote(
            body=strip_managed_roster_markers(body),
            priority=web.priority,
        )
        if content != web.raw_text:
            expected.append(
                MemoryExpectedFile(
                    path=web.path,
                    content=content,
                    detail="memory web strand roster",
                )
            )
        if web.source == "generated":
            expected.extend(
                MemoryExpectedFile(
                    path=strand.path,
                    content=strand.raw_text,
                    detail=f"generated {web.strand_noun} strand",
                )
                for strand in web.strands
            )

    return _MemoryWebRootPlan(
        expected_files=tuple(expected),
        note_overlay=note_overlay,
        core_note_bodies=core_note_bodies,
        blockers=tuple(blockers),
        warnings=validation.warnings,
    )


def memory_root_context(
    root: Path,
    linked_entries: Iterable[LinkedRepoMemoryEntry],
    *,
    project_name: str | None = None,
    manage_memory: bool = True,
    enable_amd: bool = False,
    derive_project_title: bool = False,
    chezmoi_home_roots: Iterable[Path] = (),
    include_project_agent_docs: bool = False,
    include_project_memory: bool = False,
) -> _MemoryRootContext:
    if not manage_memory:
        return _MemoryRootContext(
            amd_sync=None,
            expected_files=(),
            shim_plan=ProviderShimPlan(writes=(), deletes=()),
            additional_shim_plans=(
                agent_doc_shim_plans(root, include_root=True)
                if include_project_agent_docs
                else ()
            ),
        )

    migration = memory_migration_plan(root)
    if migration.blockers:
        return _MemoryRootContext(
            amd_sync=None,
            expected_files=(),
            shim_plan=ProviderShimPlan(writes=(), deletes=()),
            additional_shim_plans=(),
            source_memory_root=migration.source_memory_root,
            blockers=migration.blockers,
        )

    retired_note_paths = (
        *_retired_note_paths(root, include_project_memory=include_project_memory),
        *_retired_artifact_relations_note_path(root),
        *_retired_task_types_note_path(
            root, include_project_memory=include_project_memory
        ),
        *_retired_task_types_strand_paths(
            root, include_project_memory=include_project_memory
        ),
    )
    root_resolved = root.resolve(strict=False)
    excluded_note_paths = frozenset(
        path.resolve(strict=False).relative_to(root_resolved).as_posix()
        for path in retired_note_paths
    )
    memory_web_plan = _memory_web_root_plan(
        root,
        source_memory_root=migration.source_memory_root,
        include_project_memory=include_project_memory,
    )
    if memory_web_plan.blockers:
        return _MemoryRootContext(
            amd_sync=None,
            expected_files=(),
            shim_plan=ProviderShimPlan(writes=(), deletes=()),
            additional_shim_plans=(),
            source_memory_root=migration.source_memory_root,
            blockers=memory_web_plan.blockers,
            warnings=memory_web_plan.warnings,
        )

    generated_sase_body, sase_render_error = render_generated_sase_memory_body(
        root, linked_entries, project_name=project_name
    )
    if sase_render_error is not None or generated_sase_body is None:
        return _MemoryRootContext(
            amd_sync=None,
            expected_files=(),
            shim_plan=ProviderShimPlan(writes=(), deletes=()),
            additional_shim_plans=(),
            source_memory_root=migration.source_memory_root,
            blockers=(
                sase_render_error or "failed to render sase/memory/sase.md template",
            ),
        )
    generated_project_long_contents: dict[str, str] = {}
    if include_project_memory:
        generated_project_long_contents, generated_long_error = (
            render_generated_project_long_memory_contents()
        )
        if generated_long_error is not None:
            return _MemoryRootContext(
                amd_sync=None,
                expected_files=(),
                shim_plan=ProviderShimPlan(writes=(), deletes=()),
                additional_shim_plans=(),
                source_memory_root=migration.source_memory_root,
                blockers=(generated_long_error,),
            )
    generated_short_note_bodies = generated_short_notes(generated_sase_body)
    if memory_web_plan.core_note_bodies is not None:
        generated_short_note_bodies = {
            **generated_short_note_bodies,
            **dict(memory_web_plan.core_note_bodies),
        }
    amd_sync = _amd_sync_plan(
        root,
        enable_amd=enable_amd,
        derive_project_title=derive_project_title,
        generated_short_notes=generated_short_note_bodies,
        generated_long_notes=generated_long_notes(generated_project_long_contents),
        source_memory_root=migration.source_memory_root,
        excluded_note_paths=excluded_note_paths,
    )
    expected_files, expected_error = render_expected_memory_files(
        root,
        linked_entries,
        project_name=project_name,
        amd_sync=amd_sync,
        generated_sase_body=generated_sase_body,
        generated_project_long_contents=generated_project_long_contents,
        source_memory_root=migration.source_memory_root,
        include_project_memory=include_project_memory,
        excluded_note_paths=excluded_note_paths,
        additional_note_overlay=memory_web_plan.note_overlay,
    )
    if expected_error is not None:
        return _MemoryRootContext(
            amd_sync=amd_sync,
            expected_files=(),
            shim_plan=ProviderShimPlan(writes=(), deletes=()),
            additional_shim_plans=(),
            source_memory_root=migration.source_memory_root,
            blockers=(expected_error,),
        )
    expected_files = merge_expected_files(
        migration.expected_files,
        expected_files,
        memory_web_plan.expected_files,
    )
    shim_plan = provider_shim_plan(
        root,
        agents_content=final_agents_content(root, expected_files),
        chezmoi_home_roots=chezmoi_home_roots,
    )
    additional_shim_plans = (
        agent_doc_shim_plans(root, include_root=False)
        if include_project_agent_docs
        else ()
    )
    return _MemoryRootContext(
        amd_sync=amd_sync,
        expected_files=expected_files,
        shim_plan=shim_plan,
        additional_shim_plans=additional_shim_plans,
        memory_delete_paths=migration.delete_paths,
        retired_note_paths=retired_note_paths,
        source_memory_root=migration.source_memory_root,
        warnings=memory_web_plan.warnings,
    )


def plan_memory_root(
    root: Path,
    linked_entries: Iterable[LinkedRepoMemoryEntry],
    *,
    project_name: str | None = None,
    manage_memory: bool = True,
    enable_amd: bool = False,
    derive_project_title: bool = False,
    chezmoi_home_roots: Iterable[Path] = (),
    include_project_agent_docs: bool = False,
    include_project_memory: bool = False,
) -> MemoryRootPlan:
    context = memory_root_context(
        root,
        linked_entries,
        project_name=project_name,
        manage_memory=manage_memory,
        enable_amd=enable_amd,
        derive_project_title=derive_project_title,
        chezmoi_home_roots=chezmoi_home_roots,
        include_project_agent_docs=include_project_agent_docs,
        include_project_memory=include_project_memory,
    )
    overlay = validation_overlay_for_expected_files(root, context.expected_files)
    parent_blockers = (
        memory_parent_blockers(
            root,
            overlay=overlay,
            source_memory_root=context.source_memory_root,
            ignored_paths=context.retired_note_paths,
        )
        if manage_memory
        else ()
    )
    return MemoryRootPlan(
        root=root,
        changes=(
            compare_expected_memory_files(context.expected_files)
            + provider_shim_changes(context.shim_plan)
            + provider_shim_plan_changes(context.additional_shim_plans)
            + tuple(
                MemoryFileChange(
                    path=path,
                    operation="delete",
                    detail="remove migrated legacy memory file",
                )
                for path in context.memory_delete_paths
            )
            + tuple(
                MemoryFileChange(
                    path=path,
                    operation="delete",
                    detail="remove retired generated memory note",
                )
                for path in context.retired_note_paths
            )
        ),
        unreferenced=(
            ()
            if parent_blockers or not manage_memory
            else unreferenced_memory_files(
                root,
                overlay=overlay,
                source_memory_root=context.source_memory_root,
                ignored_paths=context.retired_note_paths,
            )
        ),
        blockers=(
            context.blockers
            + (() if context.amd_sync is None else context.amd_sync.blockers)
            + parent_blockers
            + context.shim_plan.blockers
            + provider_shim_plan_blockers(context.additional_shim_plans)
        ),
        warnings=context.warnings,
    )
