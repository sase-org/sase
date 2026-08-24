"""Planning helpers for memory root initialization."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from sase.amd._shared import ProviderShimPlan, provider_shim_plan
from sase.amd.init import (
    AmdMemorySyncPlan,
    plan_amd_memory_sync,
    plan_minimal_agents_sync,
)
from sase.memory.notes import GeneratedLongMemoryNote

from .glossary import (
    ProjectGlossaryTerms,
    is_generated_glossary_memory_content,
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
    generated_glossary_memory_relative_path,
    generated_long_notes,
    generated_short_notes,
    generated_task_types_memory_relative_path,
    render_generated_artifact_relations_memory_body,
    render_generated_glossary_memory_body,
    render_generated_project_long_memory_contents,
    render_generated_sase_memory_body,
    render_generated_task_types_memory_body,
    render_expected_memory_files,
)
from .root_rendering_task_types import is_generated_task_types_memory_content


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


def _retired_glossary_note_paths(
    root: Path, *, glossary_terms: ProjectGlossaryTerms | None
) -> tuple[Path, ...]:
    """Return a generated glossary memory note this root no longer manages.

    When *glossary_terms* has entries the path is generated, not retired. With
    no configured terms, a marked leftover from an earlier ``sase memory init``
    is deleted; an unmarked (hand-authored) note at the same path is left alone.
    """
    if glossary_terms is not None and glossary_terms.terms:
        return ()
    path = root / generated_glossary_memory_relative_path()
    if not path.exists():
        return ()
    try:
        current = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ()
    if not is_generated_glossary_memory_content(current):
        return ()
    return (path,)


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


def _glossary_collision_blocker(
    root: Path, *, glossary_terms: ProjectGlossaryTerms | None
) -> str | None:
    """Return a blocker when generated glossary output would overwrite a user note."""
    if glossary_terms is None or not glossary_terms.terms:
        return None
    path = root / generated_glossary_memory_relative_path()
    if not path.exists():
        return None
    try:
        current = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return f"{path}: failed to inspect existing glossary memory note: {exc}"
    if is_generated_glossary_memory_content(current):
        return None
    return (
        f"{path}: refusing to overwrite unmarked glossary memory note; migrate "
        "its content into glossary entries in sase.yml or remove it before "
        "rerunning `sase memory init`"
    )


def _amd_sync_plan(
    root: Path,
    *,
    enable_amd: bool,
    derive_project_title: bool,
    generated_short_notes: dict[str, str],
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


def memory_root_context(
    root: Path,
    linked_entries: Iterable[LinkedRepoMemoryEntry],
    *,
    project_name: str | None = None,
    glossary_terms: ProjectGlossaryTerms | None = None,
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

    glossary_collision = _glossary_collision_blocker(
        root, glossary_terms=glossary_terms
    )
    if glossary_collision is not None:
        return _MemoryRootContext(
            amd_sync=None,
            expected_files=(),
            shim_plan=ProviderShimPlan(writes=(), deletes=()),
            additional_shim_plans=(),
            source_memory_root=migration.source_memory_root,
            blockers=(glossary_collision,),
        )

    retired_note_paths = (
        *_retired_note_paths(root, include_project_memory=include_project_memory),
        *_retired_glossary_note_paths(root, glossary_terms=glossary_terms),
        *_retired_task_types_note_path(
            root, include_project_memory=include_project_memory
        ),
    )
    root_resolved = root.resolve(strict=False)
    excluded_note_paths = frozenset(
        path.resolve(strict=False).relative_to(root_resolved).as_posix()
        for path in retired_note_paths
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
    generated_task_types_body: str | None = None
    generated_artifact_relations_body: str | None = None
    if include_project_memory:
        generated_task_types_body, task_types_render_error = (
            render_generated_task_types_memory_body()
        )
        if task_types_render_error is not None or generated_task_types_body is None:
            return _MemoryRootContext(
                amd_sync=None,
                expected_files=(),
                shim_plan=ProviderShimPlan(writes=(), deletes=()),
                additional_shim_plans=(),
                source_memory_root=migration.source_memory_root,
                blockers=(
                    task_types_render_error
                    or "failed to render sase/memory/task_types.md template",
                ),
            )
        generated_artifact_relations_body, artifact_relations_render_error = (
            render_generated_artifact_relations_memory_body()
        )
        if (
            artifact_relations_render_error is not None
            or generated_artifact_relations_body is None
        ):
            return _MemoryRootContext(
                amd_sync=None,
                expected_files=(),
                shim_plan=ProviderShimPlan(writes=(), deletes=()),
                additional_shim_plans=(),
                source_memory_root=migration.source_memory_root,
                blockers=(
                    artifact_relations_render_error
                    or "failed to render sase/memory/artifact_relations.md template",
                ),
            )
    generated_glossary_body: str | None = None
    if glossary_terms is not None and glossary_terms.terms:
        generated_glossary_body, glossary_render_error = (
            render_generated_glossary_memory_body(glossary_terms)
        )
        if glossary_render_error is not None or generated_glossary_body is None:
            return _MemoryRootContext(
                amd_sync=None,
                expected_files=(),
                shim_plan=ProviderShimPlan(writes=(), deletes=()),
                additional_shim_plans=(),
                source_memory_root=migration.source_memory_root,
                blockers=(
                    glossary_render_error
                    or "failed to render sase/memory/glossary.md template",
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
    amd_sync = _amd_sync_plan(
        root,
        enable_amd=enable_amd,
        derive_project_title=derive_project_title,
        generated_short_notes=generated_short_notes(
            generated_sase_body,
            generated_task_types_body,
            generated_artifact_relations_body,
            generated_glossary_body,
        ),
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
        generated_artifact_relations_body=generated_artifact_relations_body,
        generated_task_types_body=generated_task_types_body,
        generated_glossary_body=generated_glossary_body,
        generated_project_long_contents=generated_project_long_contents,
        source_memory_root=migration.source_memory_root,
        include_project_memory=include_project_memory,
        excluded_note_paths=excluded_note_paths,
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
    )


def plan_memory_root(
    root: Path,
    linked_entries: Iterable[LinkedRepoMemoryEntry],
    *,
    project_name: str | None = None,
    glossary_terms: ProjectGlossaryTerms | None = None,
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
        glossary_terms=glossary_terms,
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
    )
