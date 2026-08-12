"""Import remote pull requests into active/archive ProjectSpec Patch files."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from pathlib import Path

from sase.ace.patch.archive import extract_patch_block
from sase.ace.patch.locking import patch_lock, write_patch_atomic
from sase.ace.patch.parser import parse_project_file
from sase.ace.patch.project_spec_path import preferred_project_spec_path
from sase.ace.patch.review_field import (
    format_review_url_line,
    is_review_url_line,
)
from sase.ace.patch.storage import format_patch_block, is_patch_heading
from sase.core.external_pr_facade import canonical_pull_request_url
from sase.core.external_pr_wire import (
    ACTION_ADOPT,
    ACTION_REFRESH,
    ACTION_REPAIR_ORIGIN,
    ACTION_SKIP,
    DESTINATION_ARCHIVE,
    PR_ORIGIN_EXTERNAL,
    REASON_MARKER_ORPHAN,
    REASON_RACED_ALREADY_OWNED,
    ExternalPrImportPlanWire,
    LocalPatchWire,
)
from sase.core.patch import get_next_suffix_number
from sase.core.paths import sase_projects_dir


@dataclass(frozen=True)
class _ProjectPatchIndex:
    by_pr_key: dict[str, LocalPatchWire]
    names: set[str]
    by_name: dict[str, LocalPatchWire]


@dataclass(frozen=True)
class _ImportOutcome:
    action_taken: str
    patch_name: str | None
    destination_file: str | None
    reason: str


def read_project_patch_index(active_file: str, archive_file: str) -> _ProjectPatchIndex:
    """Read active and archive ProjectSpec files into a PR/name index."""
    by_pr_key: dict[str, LocalPatchWire] = {}
    names: set[str] = set()
    by_name: dict[str, LocalPatchWire] = {}

    for file_path, archived in ((active_file, False), (archive_file, True)):
        if not os.path.isfile(file_path):
            continue
        for patch in parse_project_file(file_path):
            local = LocalPatchWire(
                name=patch.name,
                pr_url=patch.pr_url or "",
                pr_origin=patch.pr_origin,
                status=patch.status,
                archived=archived,
                reserved=patch.status == "Reserved",
            )
            names.add(local.name)
            by_name.setdefault(local.name, local)
            pr_key = _canonical_pr_key(local.pr_url)
            if pr_key is not None:
                by_pr_key.setdefault(pr_key, local)

    return _ProjectPatchIndex(by_pr_key=by_pr_key, names=names, by_name=by_name)


def apply_external_pr_plan(
    project_key: str,
    plan: ExternalPrImportPlanWire,
    *,
    timeout: float = 30.0,
) -> _ImportOutcome:
    """Apply an external-PR import plan with active-before-archive locking."""
    active_file, archive_file = _project_files(project_key)
    if plan.action == ACTION_SKIP:
        return _ImportOutcome(
            action_taken="skipped",
            patch_name=plan.patch_name,
            destination_file=None,
            reason=plan.reason,
        )

    Path(active_file).parent.mkdir(parents=True, exist_ok=True)
    with patch_lock(active_file, timeout=timeout):
        with patch_lock(archive_file, timeout=timeout):
            index = read_project_patch_index(active_file, archive_file)

            if plan.action == ACTION_REFRESH:
                return _refresh_existing_patch(active_file, archive_file, index, plan)

            pr_key = _canonical_pr_key(plan.canonical_pr_url or "")
            if pr_key is not None and pr_key in index.by_pr_key:
                owned = index.by_pr_key[pr_key]
                return _ImportOutcome(
                    action_taken="skipped",
                    patch_name=owned.name,
                    destination_file=None,
                    reason=REASON_RACED_ALREADY_OWNED,
                )

            if plan.action == ACTION_REPAIR_ORIGIN:
                return _repair_existing_patch(
                    active_file,
                    archive_file,
                    plan,
                )
            if plan.action == ACTION_ADOPT:
                return _create_patch(active_file, archive_file, index, plan)

    return _ImportOutcome(
        action_taken="skipped",
        patch_name=plan.patch_name,
        destination_file=None,
        reason=f"unsupported_action:{plan.action}",
    )


def _project_files(project_key: str) -> tuple[str, str]:
    project_dir = sase_projects_dir() / project_key
    active_file = preferred_project_spec_path(str(project_dir), project_key)
    archive_file = preferred_project_spec_path(
        str(project_dir),
        project_key,
        archive=True,
    )
    return active_file, archive_file


def project_patch_files(project_key: str) -> tuple[str, str]:
    """Return active and archive ProjectSpec files for *project_key*."""
    return _project_files(project_key)


def _canonical_pr_key(pr_url: str) -> str | None:
    canonical = canonical_pull_request_url(pr_url)
    return canonical.key if canonical is not None else None


def _create_patch(
    active_file: str,
    archive_file: str,
    index: _ProjectPatchIndex,
    plan: ExternalPrImportPlanWire,
) -> _ImportOutcome:
    patch_name = _resolve_patch_name(index, plan)
    if patch_name in index.names:
        return _ImportOutcome(
            action_taken="skipped",
            patch_name=patch_name,
            destination_file=None,
            reason="raced_name_exists",
        )

    destination_file = (
        archive_file if plan.destination == DESTINATION_ARCHIVE else active_file
    )
    block = format_patch_block(
        name=patch_name,
        description=plan.description,
        pr_url=plan.canonical_pr_url,
        pr_origin=plan.pr_origin,
        status=plan.status,
    )
    _append_patch_block(destination_file, block, patch_name)
    return _ImportOutcome(
        action_taken="created",
        patch_name=patch_name,
        destination_file=destination_file,
        reason=plan.reason,
    )


def _resolve_patch_name(
    index: _ProjectPatchIndex,
    plan: ExternalPrImportPlanWire,
) -> str:
    if plan.patch_name and plan.reason == REASON_MARKER_ORPHAN:
        return plan.patch_name
    if plan.patch_name and plan.pr_origin != PR_ORIGIN_EXTERNAL:
        return plan.patch_name
    base = plan.name_base or plan.patch_name or "external_pr"
    suffix = get_next_suffix_number(base, index.names)
    return f"{base}_{suffix}"


def _append_patch_block(destination_file: str, block: str, patch_name: str) -> None:
    destination = Path(destination_file)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        content = destination.read_text(encoding="utf-8")
    except FileNotFoundError:
        content = ""
    write_patch_atomic(destination_file, f"{content}{block}", f"Import PR {patch_name}")


def _refresh_existing_patch(
    active_file: str,
    archive_file: str,
    index: _ProjectPatchIndex,
    plan: ExternalPrImportPlanWire,
) -> _ImportOutcome:
    patch_name = plan.patch_name
    if not patch_name:
        return _ImportOutcome(
            action_taken="skipped",
            patch_name=None,
            destination_file=None,
            reason="missing_patch_name",
        )

    current = index.by_name.get(patch_name)
    pr_key = _canonical_pr_key(plan.canonical_pr_url or "")
    still_owned = (
        current is not None
        and current.pr_origin == PR_ORIGIN_EXTERNAL
        and pr_key is not None
        and _canonical_pr_key(current.pr_url) == pr_key
    )
    if not still_owned:
        return _ImportOutcome(
            action_taken="skipped",
            patch_name=patch_name,
            destination_file=None,
            reason=REASON_RACED_ALREADY_OWNED,
        )

    source_file = _file_containing_patch(active_file, archive_file, patch_name)
    if source_file is None:
        return _ImportOutcome(
            action_taken="skipped",
            patch_name=patch_name,
            destination_file=None,
            reason="marker_target_missing",
        )

    _rewrite_patch_status(source_file, patch_name, plan.status)
    destination_file = source_file
    if source_file == active_file and plan.destination == DESTINATION_ARCHIVE:
        if _move_patch_to_archive_locked(active_file, archive_file, patch_name):
            destination_file = archive_file

    return _ImportOutcome(
        action_taken="refreshed",
        patch_name=patch_name,
        destination_file=destination_file,
        reason=plan.reason,
    )


def _rewrite_patch_status(file_path: str, patch_name: str, status: str) -> None:
    path = Path(file_path)
    lines = path.read_text(encoding="utf-8").splitlines(True)
    bounds = _patch_line_bounds(lines, patch_name)
    if bounds is None:
        return
    start, end = bounds
    block = list(lines[start:end])
    idx = _find_line(block, lambda value: value.startswith("STATUS: "))
    if idx is not None:
        block[idx] = f"STATUS: {status}\n"
    lines[start:end] = block
    write_patch_atomic(file_path, "".join(lines), f"Refresh PR status {patch_name}")


def _repair_existing_patch(
    active_file: str,
    archive_file: str,
    plan: ExternalPrImportPlanWire,
) -> _ImportOutcome:
    patch_name = plan.patch_name
    if not patch_name:
        return _ImportOutcome(
            action_taken="skipped",
            patch_name=None,
            destination_file=None,
            reason="missing_patch_name",
        )

    source_file = _file_containing_patch(active_file, archive_file, patch_name)
    if source_file is None:
        return _ImportOutcome(
            action_taken="skipped",
            patch_name=patch_name,
            destination_file=None,
            reason="marker_target_missing",
        )

    _rewrite_patch_fields(source_file, patch_name, plan)
    destination_file = source_file
    if source_file == active_file and plan.destination == DESTINATION_ARCHIVE:
        if _move_patch_to_archive_locked(active_file, archive_file, patch_name):
            destination_file = archive_file

    return _ImportOutcome(
        action_taken="repaired",
        patch_name=patch_name,
        destination_file=destination_file,
        reason=plan.reason,
    )


def _file_containing_patch(
    active_file: str,
    archive_file: str,
    patch_name: str,
) -> str | None:
    for file_path in (active_file, archive_file):
        if not os.path.isfile(file_path):
            continue
        lines = Path(file_path).read_text(encoding="utf-8").splitlines(True)
        block, _ = extract_patch_block(lines, patch_name)
        if block is not None:
            return file_path
    return None


def _move_patch_to_archive_locked(
    active_file: str,
    archive_file: str,
    patch_name: str,
) -> bool:
    active_path = Path(active_file)
    if not active_path.is_file():
        return False
    source_lines = active_path.read_text(encoding="utf-8").splitlines(True)
    extracted, remaining = extract_patch_block(source_lines, patch_name)
    if extracted is None:
        return False

    archive_path = Path(archive_file)
    try:
        archive_content = archive_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        archive_content = ""
    if archive_content and not archive_content.endswith("\n\n"):
        if not archive_content.endswith("\n"):
            archive_content += "\n"
        archive_content += "\n"
    archive_content += "".join(extracted)
    if not archive_content.endswith("\n"):
        archive_content += "\n"

    archive_path.parent.mkdir(parents=True, exist_ok=True)
    write_patch_atomic(archive_file, archive_content, f"Archive PR {patch_name}")
    write_patch_atomic(
        active_file, "".join(remaining), f"Remove archived PR {patch_name}"
    )
    return True


def _rewrite_patch_fields(
    file_path: str,
    patch_name: str,
    plan: ExternalPrImportPlanWire,
) -> None:
    path = Path(file_path)
    lines = path.read_text(encoding="utf-8").splitlines(True)
    bounds = _patch_line_bounds(lines, patch_name)
    if bounds is None:
        return
    start, end = bounds
    block = list(lines[start:end])
    if _is_reserved_stub(block):
        replacement = format_patch_block(
            name=patch_name,
            description=plan.description,
            pr_url=plan.canonical_pr_url,
            pr_origin="sase",
            status=plan.status,
        ).splitlines(True)
        lines[start:end] = replacement
    else:
        block = _ensure_description(block, plan.description)
        block = _ensure_pr_url(block, plan.canonical_pr_url)
        block = _set_pr_origin(block, "sase")
        block = _replace_reserved_status(block, plan.status)
        lines[start:end] = block
    write_patch_atomic(file_path, "".join(lines), f"Repair PR origin {patch_name}")


def _patch_line_bounds(
    lines: list[str],
    patch_name: str,
) -> tuple[int, int] | None:
    name_idx = next(
        (
            index
            for index, line in enumerate(lines)
            if line.startswith("NAME: ") and line[6:].strip() == patch_name
        ),
        None,
    )
    if name_idx is None:
        return None
    start = name_idx
    while start > 0 and lines[start - 1].strip() == "":
        start -= 1
    if start > 0 and is_patch_heading(lines[start - 1]):
        start -= 1

    end = name_idx + 1
    while end < len(lines):
        line = lines[end]
        if line.startswith("NAME: ") or is_patch_heading(line):
            break
        end += 1
    return start, end


def _is_reserved_stub(block: list[str]) -> bool:
    non_blank = [line.strip() for line in block if line.strip()]
    return (
        len(non_blank) == 2
        and non_blank[0].startswith("NAME: ")
        and non_blank[1] == "STATUS: Reserved"
    )


def _ensure_description(block: list[str], description: str) -> list[str]:
    desc_idx = _find_line(block, lambda line: line.startswith("DESCRIPTION:"))
    if desc_idx is None:
        insert_at = _find_line(block, lambda line: line.startswith("NAME: "))
        insert_at = 1 if insert_at is None else insert_at + 1
        return (
            block[:insert_at]
            + ["DESCRIPTION:\n", *_description_lines(description)]
            + block[insert_at:]
        )
    next_field = _next_field_index(block, desc_idx + 1)
    desc_lines = block[desc_idx + 1 : next_field]
    has_text = any(line.startswith("  ") and line.strip() for line in desc_lines)
    if has_text:
        return block
    return block[: desc_idx + 1] + _description_lines(description) + block[next_field:]


def _ensure_pr_url(block: list[str], pr_url: str | None) -> list[str]:
    if not pr_url:
        return block
    if _find_line(block, is_review_url_line) is not None:
        return block
    insert_at = _field_insert_index(block)
    return block[:insert_at] + [format_review_url_line(pr_url)] + block[insert_at:]


def _set_pr_origin(block: list[str], pr_origin: str) -> list[str]:
    line = f"PR_ORIGIN: {pr_origin}\n"
    idx = _find_line(block, lambda value: value.startswith("PR_ORIGIN: "))
    if idx is not None:
        block[idx] = line
        return block
    insert_at = _field_insert_index(block)
    return block[:insert_at] + [line] + block[insert_at:]


def _replace_reserved_status(block: list[str], status: str) -> list[str]:
    idx = _find_line(block, lambda value: value.startswith("STATUS: "))
    if idx is not None and block[idx][8:].strip() == "Reserved":
        block[idx] = f"STATUS: {status}\n"
    return block


def _field_insert_index(block: list[str]) -> int:
    for prefix in ("BUG: ", "STATUS: "):

        def _starts_with_prefix(value: str, prefix: str = prefix) -> bool:
            return value.startswith(prefix)

        idx = _find_line(block, _starts_with_prefix)
        if idx is not None:
            return idx
    return len(block)


def _next_field_index(block: list[str], start: int) -> int:
    for index in range(start, len(block)):
        line = block[index]
        if _is_field_line(line):
            return index
    return len(block)


def _is_field_line(line: str) -> bool:
    return (
        line.startswith("NAME: ")
        or line.startswith("DESCRIPTION:")
        or line.startswith("PARENT: ")
        or is_review_url_line(line)
        or line.startswith("PR_ORIGIN: ")
        or line.startswith("BUG: ")
        or line.startswith("STATUS: ")
        or line.startswith("REFS:")
        or line.startswith("STITCHES:")
        or line.startswith("COMMITS:")
        or line.startswith("HOOKS:")
        or line.startswith("COMMENTS:")
        or line.startswith("MENTORS:")
        or line.startswith("TIMESTAMPS:")
        or line.startswith("DELTAS:")
    )


def _description_lines(description: str) -> list[str]:
    return [f"  {line}\n" for line in description.strip().split("\n")]


def _find_line(
    lines: list[str],
    predicate: Callable[[str], bool],
) -> int | None:
    for index, line in enumerate(lines):
        if predicate(line):
            return index
    return None


__all__ = [
    "apply_external_pr_plan",
    "project_patch_files",
    "read_project_patch_index",
]
