"""Import remote pull requests into active/archive ProjectSpec Patch files."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
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


class _ExternalPrImportBatch:
    """Locked, in-memory ProjectSpec batch for external PR mirror mutations."""

    def __init__(self, active_file: str, archive_file: str) -> None:
        self.active_file = active_file
        self.archive_file = archive_file
        self.index = read_project_patch_index(active_file, archive_file)
        self._contents = {
            active_file: _read_text(active_file),
            archive_file: _read_text(archive_file),
        }
        self._changed: set[str] = set()

    def local_patches(self) -> tuple[LocalPatchWire, ...]:
        return tuple(self.index.by_name.values())

    def apply(self, plan: ExternalPrImportPlanWire) -> _ImportOutcome:
        if plan.action == ACTION_SKIP:
            return _ImportOutcome(
                action_taken="skipped",
                patch_name=plan.patch_name,
                destination_file=None,
                reason=plan.reason,
            )

        if plan.action == ACTION_REFRESH:
            return self._refresh_existing_patch(plan)

        pr_key = _canonical_pr_key(plan.canonical_pr_url or "")
        if pr_key is not None and pr_key in self.index.by_pr_key:
            owned = self.index.by_pr_key[pr_key]
            return _ImportOutcome(
                action_taken="skipped",
                patch_name=owned.name,
                destination_file=None,
                reason=REASON_RACED_ALREADY_OWNED,
            )

        if plan.action == ACTION_REPAIR_ORIGIN:
            return self._repair_existing_patch(plan)
        if plan.action == ACTION_ADOPT:
            return self._create_patch(plan)

        return _ImportOutcome(
            action_taken="skipped",
            patch_name=plan.patch_name,
            destination_file=None,
            reason=f"unsupported_action:{plan.action}",
        )

    def commit(self) -> None:
        for file_path in (self.archive_file, self.active_file):
            if file_path in self._changed:
                Path(file_path).parent.mkdir(parents=True, exist_ok=True)
                write_patch_atomic(
                    file_path,
                    self._contents[file_path],
                    "Apply external PR mirror batch",
                )

    def _create_patch(self, plan: ExternalPrImportPlanWire) -> _ImportOutcome:
        patch_name = _resolve_patch_name(self.index, plan)
        if patch_name in self.index.names:
            return _ImportOutcome(
                action_taken="skipped",
                patch_name=patch_name,
                destination_file=None,
                reason="raced_name_exists",
            )

        destination_file = (
            self.archive_file
            if plan.destination == DESTINATION_ARCHIVE
            else self.active_file
        )
        block = format_patch_block(
            name=patch_name,
            description=plan.description,
            pr_url=plan.canonical_pr_url,
            pr_origin=plan.pr_origin,
            status=plan.status,
        )
        self._append_patch_block(destination_file, block)
        _index_replace_patch(
            self.index,
            _local_patch_from_plan(
                patch_name,
                plan,
                archived=destination_file == self.archive_file,
            ),
        )
        return _ImportOutcome(
            action_taken="created",
            patch_name=patch_name,
            destination_file=destination_file,
            reason=plan.reason,
        )

    def _refresh_existing_patch(self, plan: ExternalPrImportPlanWire) -> _ImportOutcome:
        patch_name = plan.patch_name
        if not patch_name:
            return _ImportOutcome(
                action_taken="skipped",
                patch_name=None,
                destination_file=None,
                reason="missing_patch_name",
            )

        current = self.index.by_name.get(patch_name)
        pr_key = _canonical_pr_key(plan.canonical_pr_url or "")
        still_owned = (
            current is not None
            and current.pr_origin == PR_ORIGIN_EXTERNAL
            and pr_key is not None
            and _canonical_pr_key(current.pr_url) == pr_key
        )
        if not still_owned or current is None:
            return _ImportOutcome(
                action_taken="skipped",
                patch_name=patch_name,
                destination_file=None,
                reason=REASON_RACED_ALREADY_OWNED,
            )

        source_file = self._file_containing_patch(patch_name, current)
        if source_file is None:
            return _ImportOutcome(
                action_taken="skipped",
                patch_name=patch_name,
                destination_file=None,
                reason="marker_target_missing",
            )

        self._rewrite_patch_status(source_file, patch_name, plan.status)
        destination_file = source_file
        if source_file == self.active_file and plan.destination == DESTINATION_ARCHIVE:
            if self._move_patch_to_archive(patch_name):
                destination_file = self.archive_file

        _index_replace_patch(
            self.index,
            LocalPatchWire(
                name=current.name,
                pr_url=current.pr_url,
                pr_origin=current.pr_origin,
                status=plan.status,
                archived=destination_file == self.archive_file,
                reserved=plan.status == "Reserved",
            ),
        )
        return _ImportOutcome(
            action_taken="refreshed",
            patch_name=patch_name,
            destination_file=destination_file,
            reason=plan.reason,
        )

    def _repair_existing_patch(self, plan: ExternalPrImportPlanWire) -> _ImportOutcome:
        patch_name = plan.patch_name
        if not patch_name:
            return _ImportOutcome(
                action_taken="skipped",
                patch_name=None,
                destination_file=None,
                reason="missing_patch_name",
            )

        current = self.index.by_name.get(patch_name)
        source_file = self._file_containing_patch(patch_name, current)
        if source_file is None:
            return _ImportOutcome(
                action_taken="skipped",
                patch_name=patch_name,
                destination_file=None,
                reason="marker_target_missing",
            )

        self._rewrite_patch_fields(source_file, patch_name, plan)
        destination_file = source_file
        if source_file == self.active_file and plan.destination == DESTINATION_ARCHIVE:
            if self._move_patch_to_archive(patch_name):
                destination_file = self.archive_file

        status = plan.status if current is None or current.reserved else current.status
        _index_replace_patch(
            self.index,
            LocalPatchWire(
                name=patch_name,
                pr_url=plan.canonical_pr_url or (current.pr_url if current else ""),
                pr_origin="sase",
                status=status,
                archived=destination_file == self.archive_file,
                reserved=status == "Reserved",
            ),
        )
        return _ImportOutcome(
            action_taken="repaired",
            patch_name=patch_name,
            destination_file=destination_file,
            reason=plan.reason,
        )

    def _append_patch_block(self, destination_file: str, block: str) -> None:
        self._set_content(
            destination_file, f"{self._contents[destination_file]}{block}"
        )

    def _file_containing_patch(
        self,
        patch_name: str,
        current: LocalPatchWire | None,
    ) -> str | None:
        preferred = (
            self.archive_file
            if current is not None and current.archived
            else self.active_file
        )
        for file_path in (preferred, self.active_file, self.archive_file):
            lines = self._contents[file_path].splitlines(True)
            block, _ = extract_patch_block(lines, patch_name)
            if block is not None:
                return file_path
        return None

    def _rewrite_patch_status(
        self,
        file_path: str,
        patch_name: str,
        status: str,
    ) -> None:
        lines = self._contents[file_path].splitlines(True)
        bounds = _patch_line_bounds(lines, patch_name)
        if bounds is None:
            return
        start, end = bounds
        block = list(lines[start:end])
        idx = _find_line(block, lambda value: value.startswith("STATUS: "))
        if idx is not None:
            block[idx] = f"STATUS: {status}\n"
        lines[start:end] = block
        self._set_content(file_path, "".join(lines))

    def _rewrite_patch_fields(
        self,
        file_path: str,
        patch_name: str,
        plan: ExternalPrImportPlanWire,
    ) -> None:
        lines = self._contents[file_path].splitlines(True)
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
        self._set_content(file_path, "".join(lines))

    def _move_patch_to_archive(self, patch_name: str) -> bool:
        source_lines = self._contents[self.active_file].splitlines(True)
        extracted, remaining = extract_patch_block(source_lines, patch_name)
        if extracted is None:
            return False

        archive_content = self._contents[self.archive_file]
        if archive_content and not archive_content.endswith("\n\n"):
            if not archive_content.endswith("\n"):
                archive_content += "\n"
            archive_content += "\n"
        archive_content += "".join(extracted)
        if not archive_content.endswith("\n"):
            archive_content += "\n"

        self._set_content(self.archive_file, archive_content)
        self._set_content(self.active_file, "".join(remaining))
        return True

    def _set_content(self, file_path: str, content: str) -> None:
        if self._contents[file_path] != content:
            self._contents[file_path] = content
            self._changed.add(file_path)


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


@contextmanager
def external_pr_import_batch(
    project_key: str,
    *,
    timeout: float = 30.0,
) -> Iterator[_ExternalPrImportBatch]:
    """Yield one locked external-PR import batch for *project_key*."""
    active_file, archive_file = _project_files(project_key)
    Path(active_file).parent.mkdir(parents=True, exist_ok=True)
    with patch_lock(active_file, timeout=timeout):
        with patch_lock(archive_file, timeout=timeout):
            batch = _ExternalPrImportBatch(active_file, archive_file)
            yield batch
            batch.commit()


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


def _read_text(file_path: str) -> str:
    try:
        return Path(file_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _local_patch_from_plan(
    patch_name: str,
    plan: ExternalPrImportPlanWire,
    *,
    archived: bool,
) -> LocalPatchWire:
    return LocalPatchWire(
        name=patch_name,
        pr_url=plan.canonical_pr_url or "",
        pr_origin=plan.pr_origin,
        status=plan.status,
        archived=archived,
        reserved=plan.status == "Reserved",
    )


def _index_replace_patch(
    index: _ProjectPatchIndex,
    local: LocalPatchWire,
) -> None:
    previous = index.by_name.get(local.name)
    if previous is not None:
        previous_key = _canonical_pr_key(previous.pr_url)
        if (
            previous_key is not None
            and index.by_pr_key.get(previous_key) is not None
            and index.by_pr_key[previous_key].name == local.name
        ):
            del index.by_pr_key[previous_key]

    index.names.add(local.name)
    index.by_name[local.name] = local
    pr_key = _canonical_pr_key(local.pr_url)
    if pr_key is not None:
        index.by_pr_key[pr_key] = local


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
    "external_pr_import_batch",
    "project_patch_files",
    "read_project_patch_index",
]
