"""Apply helpers for memory root initialization."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from sase.amd._agents_doc import is_managed_agents_document
from sase.amd._shared import ProviderShimPlan, apply_planned_delete, read_text
from sase.amd.constants import AGENTS_SOURCE_FILENAMES

from .inventory import unreferenced_memory_files
from .models import LinkedRepoMemoryEntry, MemoryExpectedFile, MemoryRootResult
from .root_planning import memory_root_context


def _write_expected_file(expected: MemoryExpectedFile) -> bool:
    if expected.write_policy == "create_if_missing" and expected.path.exists():
        return False
    try:
        if expected.path.exists():
            if isinstance(expected.content, bytes):
                current: str | bytes = expected.path.read_bytes()
            else:
                current = expected.path.read_text(encoding="utf-8")
            if current == expected.content:
                return False
    except (OSError, UnicodeDecodeError):
        pass
    expected.path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(expected.content, bytes):
        expected.path.write_bytes(expected.content)
    else:
        expected.path.write_text(expected.content, encoding="utf-8")
    return True


def _apply_expected_memory_files(
    expected_files: Iterable[MemoryExpectedFile],
) -> tuple[Path, ...]:
    written: list[Path] = []
    for expected in expected_files:
        if _write_expected_file(expected):
            written.append(expected.path)
    return tuple(written)


def _apply_provider_shim_plan(plan: ProviderShimPlan) -> tuple[Path, ...]:
    written: list[Path] = []
    for write in plan.writes:
        write.path.parent.mkdir(parents=True, exist_ok=True)
        write.path.write_text(write.content, encoding="utf-8")
        written.append(write.path)
    return tuple(written)


def _apply_provider_shim_plans(plans: Iterable[ProviderShimPlan]) -> tuple[Path, ...]:
    return tuple(path for plan in plans for path in _apply_provider_shim_plan(plan))


def _delete_provider_shim_paths(plan: ProviderShimPlan) -> tuple[Path, ...]:
    deleted: list[Path] = []
    for delete in plan.deletes:
        did_delete, delete_error = apply_planned_delete(delete)
        if delete_error is not None:
            raise OSError(delete_error)
        if did_delete:
            deleted.append(delete.path)
    return tuple(deleted)


def _delete_provider_shim_plan_paths(
    plans: Iterable[ProviderShimPlan],
) -> tuple[Path, ...]:
    return tuple(path for plan in plans for path in _delete_provider_shim_paths(plan))


def _delete_stale_static_agents(paths: Iterable[Path]) -> tuple[Path, ...]:
    deleted: list[Path] = []
    for path in paths:
        if not path.exists():
            continue
        text, error = read_text(path)
        if error is not None or text is None:
            raise OSError(error or f"{path}: failed to read file before delete")
        if not is_managed_agents_document(text):
            raise OSError(f"{path}: refusing to delete custom AGENTS.md content")
        try:
            path.unlink()
        except OSError as exc:
            raise OSError(f"{path}: failed to delete file: {exc}") from exc
        deleted.append(path)
    return tuple(deleted)


def _delete_retired_note_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    deleted: list[Path] = []
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        deleted.append(path)
        try:
            path.parent.rmdir()
        except OSError:
            pass
    return tuple(deleted)


def _delete_migrated_memory_paths(
    paths: Iterable[Path], *, root: Path
) -> tuple[Path, ...]:
    deleted: list[Path] = []
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        deleted.append(path)

    legacy_root = root / "memory"
    if legacy_root.is_dir():
        for directory in sorted(
            (path for path in legacy_root.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            try:
                directory.rmdir()
            except OSError:
                pass
        try:
            legacy_root.rmdir()
        except OSError:
            pass
    return tuple(deleted)


def _fold_source_paths(
    plans: Iterable[ProviderShimPlan],
    *,
    expected_files: Iterable[MemoryExpectedFile],
) -> tuple[Path, ...]:
    """Return user-owned AGENTS.md sources with dependent shim changes.

    An overwrite-managed AGENTS.md is a generated output even when provider
    shims copy its final content, so it must not become a foldable user source.
    """
    generated_sources = {
        expected.path.resolve(strict=False)
        for expected in expected_files
        if expected.path.name in AGENTS_SOURCE_FILENAMES
        and expected.write_policy == "overwrite"
    }
    sources: list[Path] = []
    seen: set[Path] = set()
    for plan in plans:
        source = plan.source_path
        if source is None or not (plan.writes or plan.deletes):
            continue
        resolved = source.resolve(strict=False)
        if resolved in generated_sources or resolved in seen:
            continue
        sources.append(source)
        seen.add(resolved)
    return tuple(sources)


def initialize_memory_root(
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
) -> MemoryRootResult:
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
    written = _apply_expected_memory_files(context.expected_files)
    written = (*written, *_apply_provider_shim_plan(context.shim_plan))
    written = (*written, *_apply_provider_shim_plans(context.additional_shim_plans))
    deleted = _delete_migrated_memory_paths(
        context.memory_delete_paths,
        root=root,
    )
    deleted = (*deleted, *_delete_retired_note_paths(context.retired_note_paths))
    deleted = (
        *deleted,
        *_delete_stale_static_agents(context.stale_agents_delete_paths),
    )
    deleted = (*deleted, *_delete_provider_shim_paths(context.shim_plan))
    deleted = (
        *deleted,
        *_delete_provider_shim_plan_paths(context.additional_shim_plans),
    )
    fold_source_paths = _fold_source_paths(
        (context.shim_plan, *context.additional_shim_plans),
        expected_files=context.expected_files,
    )

    return MemoryRootResult(
        root=root,
        written_paths=written,
        unreferenced=(
            unreferenced_memory_files(
                root,
                source_memory_root=(
                    root / "sase" / "memory" if manage_memory else None
                ),
                ignored_paths=context.retired_note_paths,
            )
            if manage_memory
            else ()
        ),
        deleted_paths=deleted,
        fold_source_paths=fold_source_paths,
    )
