"""Expected-file, provider-shim, and overlay helpers for memory root planning."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import cast

from sase.amd._chezmoi_template import unescape_chezmoi_literals
from sase.amd._shared import (
    ProviderShimPlan,
    is_root_agents_filename,
    provider_shim_plan,
    read_text,
)
from sase.amd.constants import AGENTS_FILENAME, AGENTS_TEMPLATE_FILENAME
from sase.amd.inventory import discover_project_agent_docs
from sase.memory.paths import CANONICAL_MEMORY_RELATIVE_ROOT

from .models import MemoryChangeOperation, MemoryExpectedFile, MemoryFileChange


def merge_expected_files(
    *groups: Iterable[MemoryExpectedFile],
) -> tuple[MemoryExpectedFile, ...]:
    merged: dict[Path, MemoryExpectedFile] = {}
    for group in groups:
        for expected in group:
            merged[expected.path.resolve(strict=False)] = expected
    return tuple(merged.values())


def compare_expected_memory_files(
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
                    detail=_expected_file_drift_detail(expected, current),
                    new_content=expected.content,
                )
            )
    return tuple(changes)


def _expected_file_drift_detail(
    expected: MemoryExpectedFile, current: str | bytes
) -> str:
    """Return a digest-aware snapshot detail, else the generic expected-file note."""
    if expected.path.name == "artifact_relations.json":
        return "artifact relation registry snapshot changed; run `sase memory init`"
    if expected.path.name != "task_types.json":
        return expected.detail
    if not isinstance(current, str) or not isinstance(expected.content, str):
        return expected.detail
    from sase.task_types import (
        describe_task_type_snapshot_drift,
        get_task_type_registry,
    )

    detail = describe_task_type_snapshot_drift(
        current,
        expected.content,
        registry=get_task_type_registry(),
    )
    return detail or expected.detail


def provider_shim_changes(plan: ProviderShimPlan) -> tuple[MemoryFileChange, ...]:
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


def agent_doc_shim_plans(
    root: Path, *, include_root: bool
) -> tuple[ProviderShimPlan, ...]:
    root_resolved = _resolved(root)
    root_agents = {
        _resolved(root_resolved / AGENTS_FILENAME),
        _resolved(root_resolved / AGENTS_TEMPLATE_FILENAME),
    }
    plans: list[ProviderShimPlan] = []
    for agents_path in discover_project_agent_docs(root_resolved):
        if not include_root and _resolved(agents_path) in root_agents:
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


def provider_shim_plan_blockers(
    plans: Iterable[ProviderShimPlan],
) -> tuple[str, ...]:
    return tuple(blocker for plan in plans for blocker in plan.blockers)


def provider_shim_plan_changes(
    plans: Iterable[ProviderShimPlan],
) -> tuple[MemoryFileChange, ...]:
    return tuple(change for plan in plans for change in provider_shim_changes(plan))


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


def validation_overlay_for_expected_files(
    root: Path,
    expected_files: Iterable[MemoryExpectedFile],
) -> dict[Path, str]:
    overlay: dict[Path, str] = {}
    agents_path = (root / AGENTS_FILENAME).resolve(strict=False)
    root_resolved = root.resolve(strict=False)
    for expected in expected_files:
        if isinstance(expected.content, bytes):
            continue
        resolved = expected.path.resolve(strict=False)
        if _is_memory_markdown_path(root, expected.path):
            overlay[resolved] = expected.content
            continue
        is_root_agents = (
            is_root_agents_filename(expected.path.name)
            and expected.path.parent.resolve(strict=False) == root_resolved
        )
        if is_root_agents and (
            expected.write_policy == "overwrite"
            or (
                expected.write_policy == "create_if_missing"
                and not expected.path.exists()
            )
        ):
            overlay[resolved] = expected.content
            overlay[agents_path] = unescape_chezmoi_literals(expected.content)
    return overlay


def final_agents_content(
    root: Path, expected_files: Iterable[MemoryExpectedFile]
) -> str:
    """Return the root's final ``AGENTS.md`` content for provider copies.

    Provider files are byte-for-byte copies of ``AGENTS.md``. The final content
    is the managed render (or rendered minimal template) whenever ``AGENTS.md``
    or ``AGENTS.md.tmpl`` is (re)written, and the existing on-disk content when
    the minimal template is ``create_if_missing`` and the file already exists
    (so we never copy a stale render over an untouched user file).
    """
    root_resolved = root.resolve(strict=False)
    for expected in expected_files:
        if not is_root_agents_filename(expected.path.name):
            continue
        if expected.path.parent.resolve(strict=False) != root_resolved:
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
