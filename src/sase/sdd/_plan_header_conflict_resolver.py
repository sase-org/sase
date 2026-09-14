"""Resolve generated plan-header provenance conflicts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

from sase.bead.conflict_resolver_git import (
    git_add,
    read_git_show,
    unmerged_stages,
    upstream_and_local_stages,
)
from sase.sdd._paths import is_month_dir_name
from sase.sdd.plan_header_block import (
    PlanHeaderDisposition,
    PlanHeaderEntry,
    PlanHeaderSection,
    PlanHeaderSectionKind,
    parse_plan_header_block,
    replace_plan_header_block,
)
from sase.sdd.plan_header_writes import (
    merge_plan_header_agent_entries,
    merge_plan_header_commit_entries,
)

_GENERATED_KINDS = {
    PlanHeaderSectionKind.AGENTS,
    PlanHeaderSectionKind.COMMITS,
}


class _ParsedPlanHeader(Protocol):
    @property
    def disposition(self) -> PlanHeaderDisposition: ...

    @property
    def reason(self) -> str | None: ...

    @property
    def sections(self) -> tuple[PlanHeaderSection, ...]: ...

    @property
    def body(self) -> str: ...


@dataclass(frozen=True)
class _PlanHeaderConflictResolution:
    ok: bool
    message: str
    resolved_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class _ParsedStage:
    stage: int
    document: str
    parsed: _ParsedPlanHeader


@dataclass(frozen=True)
class _PlanSignature:
    frontmatter_prefix: str
    sections: tuple[PlanHeaderSection, ...]
    body: str


@dataclass(frozen=True)
class _PreparedPlanMerge:
    ok: bool
    message: str
    content: str | None = None


def is_plan_header_conflict_path(repo_root: Path, path: str) -> bool:
    """Return whether *path* is a parseable month-sharded plan Markdown conflict."""

    if not _is_plan_markdown_path(path):
        return False
    try:
        stages = unmerged_stages(repo_root, path)
        if not stages:
            return False
        parsed = tuple(_read_stage(repo_root, path, stage) for stage in stages)
    except Exception:  # noqa: BLE001 - leave ambiguous paths to the generic gate.
        return False
    return any(_has_generated_section(stage) for stage in parsed)


def resolve_plan_header_conflicts(
    repo_root: Path,
    paths: tuple[str, ...],
) -> _PlanHeaderConflictResolution:
    """Resolve preclaimed plan-header conflicts, failing closed on authored edits."""

    if not paths:
        return _PlanHeaderConflictResolution(True, "no plan-header conflicts")

    prepared: list[tuple[str, str]] = []
    for path in sorted(paths):
        if not is_plan_header_conflict_path(repo_root, path):
            return _PlanHeaderConflictResolution(
                False,
                "unsupported plan-header conflicts: " + path,
            )
        result = _prepare_plan_header_merge(repo_root, path)
        if not result.ok:
            return _PlanHeaderConflictResolution(False, result.message)
        assert result.content is not None
        prepared.append((path, result.content))

    for path, content in prepared:
        target = repo_root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    git_add(repo_root, [path for path, _content in prepared])
    resolved = tuple(path for path, _content in prepared)
    return _PlanHeaderConflictResolution(
        True,
        "resolved plan-header conflicts: " + ", ".join(resolved),
        resolved,
    )


def _prepare_plan_header_merge(repo_root: Path, path: str) -> _PreparedPlanMerge:
    stages = unmerged_stages(repo_root, path)
    if stages == frozenset({1, 2, 3}):
        present = tuple(_read_stage(repo_root, path, stage) for stage in (1, 2, 3))
        upstream_stage, local_stage = upstream_and_local_stages(repo_root)
        current = next(stage for stage in present if stage.stage == local_stage)
        theirs = next(stage for stage in present if stage.stage == upstream_stage)
    elif stages == frozenset({2, 3}):
        upstream_stage, local_stage = upstream_and_local_stages(repo_root)
        current = _read_stage(repo_root, path, local_stage)
        theirs = _read_stage(repo_root, path, upstream_stage)
        present = (current, theirs)
    elif stages in (frozenset({1, 2}), frozenset({1, 3})):
        return _PreparedPlanMerge(
            False,
            f"unsupported plan-header conflict {path}: modify/delete stages "
            + ",".join(str(stage) for stage in sorted(stages)),
        )
    else:
        return _PreparedPlanMerge(
            False,
            f"unsupported plan-header conflict {path}: unexpected stages "
            + ",".join(str(stage) for stage in sorted(stages)),
        )

    signatures = {_signature_without_generated_sections(stage) for stage in present}
    if len(signatures) != 1:
        return _PreparedPlanMerge(False, f"authored plan conflict remains in {path}")

    content = _merge_generated_sections(current, theirs)
    return _PreparedPlanMerge(True, "resolved", content)


def _read_stage(repo_root: Path, path: str, stage: int) -> _ParsedStage:
    document = read_git_show(repo_root, stage, path)
    parsed = parse_plan_header_block(document)
    if parsed.disposition is PlanHeaderDisposition.INVALID:
        reason = f": {parsed.reason}" if parsed.reason else ""
        raise ValueError(f"stage {stage} has an invalid plan header{reason}")
    return _ParsedStage(stage, document, parsed)


def _signature_without_generated_sections(stage: _ParsedStage) -> _PlanSignature:
    parsed = stage.parsed
    sections = tuple(
        section for section in parsed.sections if section.kind not in _GENERATED_KINDS
    )
    return _PlanSignature(
        frontmatter_prefix=_frontmatter_prefix(stage.document),
        sections=sections,
        body=parsed.body,
    )


def _merge_generated_sections(current: _ParsedStage, theirs: _ParsedStage) -> str:
    agents = merge_plan_header_agent_entries(
        _entries_for_section(theirs.parsed.sections, PlanHeaderSectionKind.AGENTS),
        _entries_for_section(current.parsed.sections, PlanHeaderSectionKind.AGENTS),
    )
    commits = merge_plan_header_commit_entries(
        _entries_for_section(theirs.parsed.sections, PlanHeaderSectionKind.COMMITS),
        _entries_for_section(current.parsed.sections, PlanHeaderSectionKind.COMMITS),
    )
    sections = tuple(
        section
        for section in current.parsed.sections
        if section.kind not in _GENERATED_KINDS
    ) + (
        PlanHeaderSection(kind=PlanHeaderSectionKind.AGENTS, entries=agents),
        PlanHeaderSection(kind=PlanHeaderSectionKind.COMMITS, entries=commits),
    )
    return replace_plan_header_block(
        current.document,
        sections,
        remove_legacy=False,
    )


def _entries_for_section(
    sections: tuple[PlanHeaderSection, ...],
    kind: PlanHeaderSectionKind,
) -> tuple[PlanHeaderEntry, ...]:
    section = next((section for section in sections if section.kind is kind), None)
    if section is None:
        return ()
    return section.entries


def _has_generated_section(stage: _ParsedStage) -> bool:
    return any(section.kind in _GENERATED_KINDS for section in stage.parsed.sections)


def _is_plan_markdown_path(path: str) -> bool:
    candidate = PurePosixPath(path)
    parts = candidate.parts
    if candidate.is_absolute() or ".." in parts:
        return False
    if candidate.suffix.casefold() != ".md":
        return False
    if len(parts) == 2:
        return is_month_dir_name(parts[0])
    if len(parts) == 3 and parts[0] == "plans":
        return is_month_dir_name(parts[1])
    if len(parts) == 4 and parts[:2] == ("sdd", "plans"):
        return is_month_dir_name(parts[2])
    return False


def _frontmatter_prefix(document: str) -> str:
    lines = document.splitlines(keepends=True)
    if not lines or _trim_line(lines[0]) != "---":
        return ""
    consumed = len(lines[0])
    for line in lines[1:]:
        consumed += len(line)
        if _trim_line(line) == "---":
            return document[:consumed]
    return document


def _trim_line(line: str) -> str:
    return line.rstrip("\n").rstrip("\r")


__all__ = [
    "is_plan_header_conflict_path",
    "resolve_plan_header_conflicts",
]
