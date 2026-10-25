"""Language breakdown projection for the shared Projects report.

Textual- and Rich-free: projects the existing sase-core wire (project,
portfolio, and per-repo ``languages`` plus ``role_counts``) into one breakdown
used by the card, the language table, the repo table, and Markdown.

Totals always come from Rust's identity-deduplicated aggregates
(``project.code.languages`` / ``portfolio.code.languages``). Per-repo detail
comes from each measured code repo's snapshot. Any double-counted lines from
repos shared by several projects are reported as ``overlap_lines``, never
silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass

from typing import Any

from sase.stats.project.models import ProjectStatsRepo
from sase.stats.project.view import ProjectStatsView


def repo_code_lines(snapshot: Any | None) -> int | None:
    """Return source + tests lines for one repo snapshot.

    Mirrors sase-core ``project_stats::code::code_totals``: when ``role_counts``
    is present the code total is source lines plus tests lines; otherwise it
    falls back to ``tracked_lines`` (which counts every role).
    """
    if snapshot is None:
        return None
    role_counts = snapshot.role_counts
    if role_counts is not None:
        source_lines = 0
        test_lines = 0
        for row in role_counts:
            if row.role == "source":
                source_lines = row.lines
            elif row.role == "tests":
                test_lines = row.lines
        return source_lines + test_lines
    return snapshot.tracked_lines


def repo_test_lines(snapshot: Any | None) -> int | None:
    """Return test lines for one repo snapshot, preferring ``role_counts``."""
    if snapshot is None:
        return None
    role_counts = snapshot.role_counts
    if role_counts is not None:
        for row in role_counts:
            if row.role == "tests":
                return row.lines
        return 0
    return snapshot.test_lines


@dataclass(frozen=True, slots=True)
class LanguageSlice:
    """One repo's contribution to one language."""

    project_key: str
    project_label: str
    repo_id: str
    repo_name: str
    lines: int
    files: int


@dataclass(frozen=True, slots=True)
class LanguageRow:
    """One language parent row; ``language`` is None for the ``?`` sentinel."""

    language: str | None
    lines: int
    files: int
    share: float
    slices: tuple[LanguageSlice, ...] = ()


@dataclass(frozen=True, slots=True)
class _ZeroLanguage:
    """A language with zero countable lines (files only)."""

    language: str
    files: int


@dataclass(frozen=True, slots=True)
class _UnmeasuredRepo:
    """A code repo with no snapshot."""

    project_key: str
    project_label: str
    repo_id: str
    repo_name: str
    reason: str


@dataclass(frozen=True, slots=True)
class UnclassifiedRepo:
    """A code repo with many lines in files with no recognized language."""

    project_key: str
    project_label: str
    repo_id: str
    repo_name: str
    lines: int
    files: int


_UNCLASSIFIED_MIN_LINES = 1_000
_UNCLASSIFIED_MIN_SHARE = 0.10


@dataclass(frozen=True, slots=True)
class LanguageBreakdown:
    """One subject's language breakdown (one project or the portfolio)."""

    total_lines: int
    total_files: int
    rows: tuple[LanguageRow, ...]
    zero_languages: tuple[_ZeroLanguage, ...]
    unmeasured: tuple[_UnmeasuredRepo, ...]
    overlap_lines: int
    many_projects: bool
    measured_repos: int
    configured_repos: int
    unclassified: tuple[UnclassifiedRepo, ...] = ()


def language_breakdown(view: ProjectStatsView) -> LanguageBreakdown | None:
    """Project the wire into one breakdown, or None when code is unavailable."""
    if view.code_pending:
        return None
    many = len(view.projects) > 1
    if many:
        code = view.portfolio.code
    else:
        if not view.projects:
            return None
        code = view.projects[0].code
    if code is None:
        return None
    total_lines = code.code_lines
    total_files = code.code_files
    if total_lines is None:
        return None
    if total_files is None:
        total_files = 0
    parent_languages = code.languages
    if parent_languages is None:
        parent_languages = ()

    code_repos: list[tuple[str, str, ProjectStatsRepo]] = []
    for project in view.projects:
        for repo in project.repos:
            if repo.tier == "code":
                code_repos.append((project.key, project.label, repo))
    if not code_repos:
        if total_lines == 0:
            return LanguageBreakdown(
                total_lines=total_lines,
                total_files=total_files,
                rows=(),
                zero_languages=(),
                unmeasured=(),
                overlap_lines=0,
                many_projects=many,
                measured_repos=0,
                configured_repos=code.repos_configured,
            )
        # No code repos but nonzero lines: still return empty rows; renderer
        # shows "No code lines measured." when there are no measured repos.
        return LanguageBreakdown(
            total_lines=total_lines,
            total_files=total_files,
            rows=(),
            zero_languages=tuple(
                _ZeroLanguage(language=row.name, files=row.files)
                for row in parent_languages
                if row.lines == 0
            ),
            unmeasured=(),
            overlap_lines=0,
            many_projects=many,
            measured_repos=0,
            configured_repos=code.repos_configured,
        )

    slice_map: dict[str, list[LanguageSlice]] = {}
    repo_totals: list[int] = []
    unmeasured: list[_UnmeasuredRepo] = []
    measured_count = 0
    for project_key, project_label, repo in code_repos:
        snapshot = repo.snapshot
        if snapshot is None:
            issue = repo.issue
            reason = (
                issue.message if issue is not None and issue.message else repo.status
            )
            unmeasured.append(
                _UnmeasuredRepo(
                    project_key=project_key,
                    project_label=project_label,
                    repo_id=repo.id,
                    repo_name=repo.name,
                    reason=reason or "not measured",
                )
            )
            continue
        lines = repo_code_lines(snapshot)
        if lines is None:
            issue = repo.issue
            reason = (
                issue.message if issue is not None and issue.message else repo.status
            )
            unmeasured.append(
                _UnmeasuredRepo(
                    project_key=project_key,
                    project_label=project_label,
                    repo_id=repo.id,
                    repo_name=repo.name,
                    reason=reason or "not measured",
                )
            )
            continue
        measured_count += 1
        repo_totals.append(lines)
        for lang in snapshot.languages or ():
            slice_map.setdefault(lang.name, []).append(
                LanguageSlice(
                    project_key=project_key,
                    project_label=project_label,
                    repo_id=repo.id,
                    repo_name=repo.name,
                    lines=lang.lines,
                    files=lang.files,
                )
            )

    parent_by_id: dict[str, tuple[int, int]] = {}
    for row in parent_languages:
        parent_by_id[row.name] = (row.lines, row.files)

    # Zero-line languages never become rows.
    zero_languages = tuple(
        _ZeroLanguage(language=name, files=files)
        for name, (lines, files) in sorted(parent_by_id.items())
        if lines == 0
    )

    # Known rows use Rust aggregates; slice-only ids fall back to slice sums.
    known_ids = {name for name, (lines, _files) in parent_by_id.items() if lines > 0}
    slice_only_ids = {name for name in slice_map if name not in parent_by_id}
    for name in slice_only_ids:
        total = sum(item.lines for item in slice_map[name])
        if total > 0:
            known_ids.add(name)

    rows: list[LanguageRow] = []
    for name in known_ids:
        if name in parent_by_id:
            lines, files = parent_by_id[name]
        else:
            items = slice_map.get(name, [])
            lines = sum(item.lines for item in items)
            files = sum(item.files for item in items)
        if lines <= 0:
            continue
        slices = tuple(
            sorted(
                slice_map.get(name, []),
                key=lambda item: (
                    -item.lines,
                    -item.files,
                    item.project_label.casefold(),
                    item.repo_name.casefold(),
                    item.repo_id,
                ),
            )
        )
        share = (lines / total_lines) if total_lines else 0.0
        rows.append(
            LanguageRow(
                language=name,
                lines=lines,
                files=files,
                share=share,
                slices=slices,
            )
        )
    rows.sort(
        key=lambda row: (
            -row.lines,
            -row.files,
            (row.language or "").casefold(),
        )
    )

    parent_known_lines = sum(row.lines for row in rows)
    parent_known_files = sum(row.files for row in rows)
    zero_files = sum(item.files for item in zero_languages)
    unknown_lines = total_lines - parent_known_lines
    unknown_files = total_files - parent_known_files - zero_files
    if unknown_lines < 0:
        unknown_lines = 0
    if unknown_files is None or unknown_files < 0:
        unknown_files = 0
    if unknown_lines > 0:
        unknown_slices: list[LanguageSlice] = []
        for project_key, project_label, repo in code_repos:
            snapshot = repo.snapshot
            if snapshot is None:
                continue
            repo_total = repo_code_lines(snapshot)
            if repo_total is None:
                continue
            repo_lang_lines = sum(lang.lines for lang in snapshot.languages or ())
            repo_lang_files = sum(lang.files for lang in snapshot.languages or ())
            gap_lines = repo_total - repo_lang_lines
            gap_files = _repo_file_total(snapshot) - repo_lang_files
            if gap_lines > 0:
                unknown_slices.append(
                    LanguageSlice(
                        project_key=project_key,
                        project_label=project_label,
                        repo_id=repo.id,
                        repo_name=repo.name,
                        lines=gap_lines,
                        files=max(0, gap_files),
                    )
                )
        unknown_slices.sort(
            key=lambda item: (
                -item.lines,
                -item.files,
                item.project_label.casefold(),
                item.repo_name.casefold(),
                item.repo_id,
            )
        )
        rows.append(
            LanguageRow(
                language=None,
                lines=unknown_lines,
                files=unknown_files,
                share=(unknown_lines / total_lines) if total_lines else 0.0,
                slices=tuple(unknown_slices),
            )
        )

    overlap = sum(repo_totals) - total_lines
    if overlap < 0:
        overlap = 0

    unclassified = _unclassified_repos(code_repos, many)

    return LanguageBreakdown(
        total_lines=total_lines,
        total_files=total_files,
        rows=tuple(rows),
        zero_languages=zero_languages,
        unmeasured=tuple(unmeasured),
        overlap_lines=overlap,
        many_projects=many,
        measured_repos=measured_count,
        configured_repos=code.repos_configured,
        unclassified=unclassified,
    )


def _unclassified_repos(
    code_repos: list[tuple[str, str, ProjectStatsRepo]],
    many: bool,
) -> tuple[UnclassifiedRepo, ...]:
    """Return repos with many lines in files with no recognized language."""
    by_id: dict[str, UnclassifiedRepo] = {}
    ordered: list[UnclassifiedRepo] = []
    for project_key, project_label, repo in code_repos:
        snapshot = repo.snapshot
        if snapshot is None:
            continue
        role_counts = snapshot.role_counts
        if role_counts is None:
            continue
        other_lines = 0
        other_files = 0
        for row in role_counts:
            if row.role == "other":
                other_lines = row.lines
                other_files = row.files
                break
        if other_lines < _UNCLASSIFIED_MIN_LINES:
            continue
        repo_code = repo_code_lines(snapshot)
        if repo_code is None:
            repo_code = 0
        if repo_code != 0 and other_lines < _UNCLASSIFIED_MIN_SHARE * repo_code:
            continue
        entry = UnclassifiedRepo(
            project_key=project_key,
            project_label=project_label,
            repo_id=repo.id,
            repo_name=repo.name,
            lines=other_lines,
            files=other_files,
        )
        if many:
            current = by_id.get(repo.id)
            if current is not None:
                if entry.lines <= current.lines:
                    continue
            by_id[repo.id] = entry
            continue
        ordered.append(entry)
    if many:
        ordered = list(by_id.values())
    ordered.sort(
        key=lambda item: (
            -item.lines,
            item.project_label.casefold(),
            item.repo_name.casefold(),
            item.repo_id,
        )
    )
    return tuple(ordered)


def _repo_file_total(snapshot: Any) -> int:
    role_counts = snapshot.role_counts
    if role_counts is not None:
        total = 0
        for row in role_counts:
            if row.role in ("source", "tests"):
                total += row.files
        return total
    tracked = snapshot.tracked_files
    return tracked if tracked is not None else 0


__all__ = [
    "LanguageBreakdown",
    "LanguageRow",
    "LanguageSlice",
    "UnclassifiedRepo",
    "language_breakdown",
    "repo_code_lines",
    "repo_test_lines",
]
