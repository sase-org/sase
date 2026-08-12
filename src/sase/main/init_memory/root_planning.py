"""Planning helpers for memory root initialization."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from sase.amd._shared import ProviderShimPlan, provider_shim_plan, read_text
from sase.amd.init import (
    AmdMemorySyncPlan,
    plan_amd_memory_sync,
    plan_minimal_agents_sync,
)
from sase.memory.notes import GeneratedLongMemoryNote
from sase.amd.inventory import discover_project_agent_docs
from sase.memory.paths import (
    CANONICAL_MEMORY_RELATIVE_ROOT,
    memory_layout,
    memory_write_root,
)

from .inventory import memory_parent_blockers, unreferenced_memory_files
from .models import (
    LinkedRepoMemoryEntry,
    MemoryChangeOperation,
    MemoryExpectedFile,
    MemoryFileChange,
    MemoryRootPlan,
)
from .glossary import (
    GeneratedGlossaryMemory,
    is_generated_glossary_memory_content,
)
from .root_rendering import (
    generated_glossary_memory_relative_path,
    generated_long_notes,
    generated_short_notes,
    render_generated_project_long_memory_contents,
    render_generated_sase_memory_body,
    render_expected_memory_files,
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


@dataclass(frozen=True)
class _MemoryMigrationPlan:
    source_memory_root: Path
    expected_files: tuple[MemoryExpectedFile, ...] = ()
    delete_paths: tuple[Path, ...] = ()
    blockers: tuple[str, ...] = ()


def _tree_files(root: Path) -> tuple[Path, ...]:
    if not root.is_dir():
        return ()
    return tuple(
        sorted(
            (path for path in root.rglob("*") if path.is_file()),
            key=lambda path: path.as_posix(),
        )
    )


def _tree_symlinks(root: Path) -> tuple[Path, ...]:
    if not root.is_dir():
        return ()
    return tuple(
        sorted(
            (path for path in root.rglob("*") if path.is_symlink()),
            key=lambda path: path.as_posix(),
        )
    )


def _relative_file_map(root: Path) -> dict[Path, Path]:
    return {path.relative_to(root): path for path in _tree_files(root)}


def _identical_memory_trees(canonical: Path, legacy: Path) -> bool:
    canonical_files = _relative_file_map(canonical)
    legacy_files = _relative_file_map(legacy)
    if canonical_files.keys() != legacy_files.keys():
        return False
    try:
        return all(
            canonical_files[relative].read_bytes()
            == legacy_files[relative].read_bytes()
            for relative in canonical_files
        )
    except OSError:
        return False


def _memory_migration_plan(root: Path) -> _MemoryMigrationPlan:
    compatible = memory_layout(root)
    canonical = compatible.canonical.path
    legacy = compatible.legacy[0].path
    canonical_exists = canonical.exists()
    legacy_exists = legacy.exists()

    if canonical_exists and not canonical.is_dir():
        return _MemoryMigrationPlan(
            source_memory_root=canonical,
            blockers=(f"{canonical}: canonical memory path is not a directory",),
        )
    if legacy_exists and not legacy.is_dir():
        return _MemoryMigrationPlan(
            source_memory_root=canonical,
            blockers=(f"{legacy}: legacy memory path is not a directory",),
        )
    if not legacy_exists:
        return _MemoryMigrationPlan(source_memory_root=canonical)

    legacy_symlinks = _tree_symlinks(legacy)
    if legacy_symlinks:
        rendered = ", ".join(str(path) for path in legacy_symlinks)
        return _MemoryMigrationPlan(
            source_memory_root=legacy,
            blockers=(
                "legacy memory tree contains symlinks that cannot be migrated "
                f"safely: {rendered}",
            ),
        )

    legacy_files = _tree_files(legacy)
    delete_paths = tuple(reversed(legacy_files))
    if canonical_exists:
        if not _identical_memory_trees(canonical, legacy):
            return _MemoryMigrationPlan(
                source_memory_root=canonical,
                blockers=(
                    f"memory exists in non-identical canonical and legacy trees: "
                    f"{canonical}, {legacy}; reconcile them before running init",
                ),
            )
        return _MemoryMigrationPlan(
            source_memory_root=canonical,
            delete_paths=delete_paths,
        )

    expected: list[MemoryExpectedFile] = []
    blockers: list[str] = []
    for source in legacy_files:
        relative = source.relative_to(legacy)
        try:
            content = source.read_bytes()
        except OSError as exc:
            blockers.append(f"{source}: failed to read legacy memory file: {exc}")
            continue
        expected.append(
            MemoryExpectedFile(
                path=canonical / relative,
                content=content,
                detail="migrate legacy memory file",
            )
        )
    return _MemoryMigrationPlan(
        source_memory_root=legacy,
        expected_files=tuple(expected),
        delete_paths=delete_paths,
        blockers=tuple(blockers),
    )


def _retired_note_paths(
    root: Path, *, include_project_memory: bool
) -> tuple[Path, ...]:
    """Return generated project memory notes this root no longer manages.

    A root that stopped managing project-only notes (currently: every root except a
    SASE-managed project) still deletes previously generated copies so it converges in a
    single ``sase memory init`` pass. Only a file that is byte-identical to the current
    packaged render is considered SASE-owned; a human-edited copy is left alone and
    keeps behaving as an ordinary long note.
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
    root: Path, *, generated_glossary: GeneratedGlossaryMemory | None
) -> tuple[Path, ...]:
    """Return a generated glossary memory note this root no longer manages."""
    if generated_glossary is not None:
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


def _glossary_collision_blocker(
    root: Path, *, generated_glossary: GeneratedGlossaryMemory | None
) -> str | None:
    """Return a blocker when generated glossary output would overwrite a user note."""
    if generated_glossary is None:
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


def _merge_expected_files(
    *groups: Iterable[MemoryExpectedFile],
) -> tuple[MemoryExpectedFile, ...]:
    merged: dict[Path, MemoryExpectedFile] = {}
    for group in groups:
        for expected in group:
            merged[expected.path.resolve(strict=False)] = expected
    return tuple(merged.values())


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


def _compare_expected_memory_files(
    expected_files: Iterable[MemoryExpectedFile],
) -> tuple[MemoryFileChange, ...]:
    changes: list[MemoryFileChange] = []
    for expected in expected_files:
        if not expected.path.exists():
            changes.append(
                MemoryFileChange(
                    path=expected.path,
                    operation="create",
                    detail=expected.detail,
                    new_content=expected.content,
                )
            )
            continue
        if expected.write_policy == "create_if_missing":
            continue
        try:
            if isinstance(expected.content, bytes):
                current: str | bytes = expected.path.read_bytes()
            else:
                current = expected.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            changes.append(
                MemoryFileChange(
                    path=expected.path,
                    operation=expected.stale_operation,
                    detail=expected.detail,
                    new_content=expected.content,
                )
            )
            continue
        if current != expected.content:
            changes.append(
                MemoryFileChange(
                    path=expected.path,
                    operation=expected.stale_operation,
                    detail=expected.detail,
                    new_content=expected.content,
                )
            )
    return tuple(changes)


def _provider_shim_changes(plan: ProviderShimPlan) -> tuple[MemoryFileChange, ...]:
    changes: list[MemoryFileChange] = []
    for write in plan.writes:
        if write.action.operation not in {"create", "overwrite"}:
            raise AssertionError(
                f"unexpected memory init operation: {write.action.operation}"
            )
        changes.append(
            MemoryFileChange(
                path=write.path,
                operation=cast(MemoryChangeOperation, write.action.operation),
                detail=write.action.detail,
                new_content=write.content,
            )
        )
    for delete in plan.deletes:
        changes.append(
            MemoryFileChange(
                path=delete.path,
                operation="delete",
                detail=delete.action.detail,
            )
        )
    return tuple(changes)


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _agent_doc_shim_plans(
    root: Path, *, include_root: bool
) -> tuple[ProviderShimPlan, ...]:
    root_resolved = _resolved(root)
    root_agents = _resolved(root_resolved / "AGENTS.md")
    plans: list[ProviderShimPlan] = []
    for agents_path in discover_project_agent_docs(root_resolved):
        if not include_root and _resolved(agents_path) == root_agents:
            continue
        agents_content, read_error = read_text(agents_path)
        if read_error is not None or agents_content is None:
            plans.append(
                ProviderShimPlan(
                    writes=(),
                    deletes=(),
                    blockers=(read_error or f"{agents_path}: failed to read file",),
                    source_path=agents_path,
                )
            )
            continue
        plans.append(
            provider_shim_plan(
                agents_path.parent,
                agents_content=agents_content,
            )
        )
    return tuple(plans)


def _provider_shim_plan_blockers(
    plans: Iterable[ProviderShimPlan],
) -> tuple[str, ...]:
    return tuple(blocker for plan in plans for blocker in plan.blockers)


def _provider_shim_plan_changes(
    plans: Iterable[ProviderShimPlan],
) -> tuple[MemoryFileChange, ...]:
    return tuple(change for plan in plans for change in _provider_shim_changes(plan))


def _is_memory_markdown_path(root: Path, path: Path) -> bool:
    root_resolved = root.resolve(strict=False)
    try:
        relative = path.resolve(strict=False).relative_to(root_resolved)
    except ValueError:
        return False
    if path.suffix != ".md":
        return False
    memory_prefix = CANONICAL_MEMORY_RELATIVE_ROOT.parts
    return (
        relative.parts[: len(memory_prefix)] == memory_prefix
        and len(relative.parts) == len(memory_prefix) + 1
        and relative.name != "README.md"
    )


def _validation_overlay_for_expected_files(
    root: Path,
    expected_files: Iterable[MemoryExpectedFile],
) -> dict[Path, str]:
    overlay: dict[Path, str] = {}
    agents_path = (root / "AGENTS.md").resolve(strict=False)
    for expected in expected_files:
        if isinstance(expected.content, bytes):
            continue
        resolved = expected.path.resolve(strict=False)
        if _is_memory_markdown_path(root, expected.path):
            overlay[resolved] = expected.content
            continue
        if resolved == agents_path and (
            expected.write_policy == "overwrite"
            or (
                expected.write_policy == "create_if_missing"
                and not expected.path.exists()
            )
        ):
            overlay[resolved] = expected.content
    return overlay


def _final_agents_content(
    root: Path, expected_files: Iterable[MemoryExpectedFile]
) -> str:
    """Return the root's final ``AGENTS.md`` content for provider copies.

    Provider files are byte-for-byte copies of ``AGENTS.md``. The final content
    is the managed render (or rendered minimal template) whenever ``AGENTS.md``
    is (re)written, and the existing on-disk content when the minimal template is
    ``create_if_missing`` and the file already exists (so we never copy a stale
    render over an untouched user file).
    """
    agents_path = root / "AGENTS.md"
    for expected in expected_files:
        if expected.path != agents_path:
            continue
        if isinstance(expected.content, bytes):
            continue
        if expected.write_policy == "create_if_missing" and expected.path.exists():
            try:
                return expected.path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                return expected.content
        return expected.content
    return ""


def memory_root_context(
    root: Path,
    linked_entries: Iterable[LinkedRepoMemoryEntry],
    *,
    project_name: str | None = None,
    generated_glossary: GeneratedGlossaryMemory | None = None,
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
                _agent_doc_shim_plans(root, include_root=True)
                if include_project_agent_docs
                else ()
            ),
        )

    migration = _memory_migration_plan(root)
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
        root, generated_glossary=generated_glossary
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
        *_retired_glossary_note_paths(root, generated_glossary=generated_glossary),
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
    generated_amd_long_contents = dict(generated_project_long_contents)
    if generated_glossary is not None:
        generated_amd_long_contents[
            generated_glossary_memory_relative_path().as_posix()
        ] = generated_glossary.content
    amd_sync = _amd_sync_plan(
        root,
        enable_amd=enable_amd,
        derive_project_title=derive_project_title,
        generated_short_notes=generated_short_notes(generated_sase_body),
        generated_long_notes=generated_long_notes(generated_amd_long_contents),
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
        generated_glossary=generated_glossary,
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
    expected_files = _merge_expected_files(
        migration.expected_files,
        expected_files,
    )
    shim_plan = provider_shim_plan(
        root,
        agents_content=_final_agents_content(root, expected_files),
        chezmoi_home_roots=chezmoi_home_roots,
    )
    additional_shim_plans = (
        _agent_doc_shim_plans(root, include_root=False)
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
    generated_glossary: GeneratedGlossaryMemory | None = None,
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
        generated_glossary=generated_glossary,
        manage_memory=manage_memory,
        enable_amd=enable_amd,
        derive_project_title=derive_project_title,
        chezmoi_home_roots=chezmoi_home_roots,
        include_project_agent_docs=include_project_agent_docs,
        include_project_memory=include_project_memory,
    )
    overlay = _validation_overlay_for_expected_files(root, context.expected_files)
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
            _compare_expected_memory_files(context.expected_files)
            + _provider_shim_changes(context.shim_plan)
            + _provider_shim_plan_changes(context.additional_shim_plans)
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
            + _provider_shim_plan_blockers(context.additional_shim_plans)
        ),
    )
