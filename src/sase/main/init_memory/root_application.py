"""Apply helpers for memory root initialization."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from sase.amd._shared import ProviderShimPlan, apply_planned_delete

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
    )
    written = _apply_expected_memory_files(context.expected_files)
    written = (*written, *_apply_provider_shim_plan(context.shim_plan))
    written = (*written, *_apply_provider_shim_plans(context.additional_shim_plans))
    deleted = _delete_provider_shim_paths(context.shim_plan)
    deleted = (
        *deleted,
        *_delete_provider_shim_plan_paths(context.additional_shim_plans),
    )

    return MemoryRootResult(
        root=root,
        written_paths=written,
        unreferenced=unreferenced_memory_files(root) if manage_memory else (),
        deleted_paths=deleted,
    )
