"""Frozen presentation records matching the project_stats response wire."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProjectStatsIssue:
    code: str
    message: str
    project: str | None = None
    repo: str | None = None
    hint: str | None = None


@dataclass(frozen=True, slots=True)
class _UnknownReasonCount:
    reason: str
    count: int


@dataclass(frozen=True, slots=True)
class ProjectStatsCoverage:
    configured_repos: int = 0
    measured_repos: int = 0
    partial_repos: int = 0
    unavailable_repos: int = 0
    agent_tagged_commits: int = 0
    resolved_agent_commits: int = 0
    unknown_agent_commits: int = 0
    unknown_reasons: tuple[_UnknownReasonCount, ...] = ()


@dataclass(frozen=True, slots=True)
class ProjectStatsModel:
    kind: str
    provider: str | None = None
    model: str | None = None
    model_is_alias: bool = False
    commits: int = 0
    plans: int | None = None
    plans_epic: int | None = None
    plans_tale: int | None = None
    unknown_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _ProjectStatsOutput:
    commits: int | None = None
    agent_commits: int | None = None
    agent_share: float | None = None
    plans_committed: int | None = None
    plans_epic: int | None = None
    plans_tale: int | None = None
    models: tuple[ProjectStatsModel, ...] = ()
    commit_coverage: ProjectStatsCoverage = ProjectStatsCoverage()
    plan_coverage: ProjectStatsCoverage = ProjectStatsCoverage()


@dataclass(frozen=True, slots=True)
class _ProjectStatsLifetime:
    first_commit_ts: int | None = None
    last_commit_ts: int | None = None
    age_days: int | None = None
    active_days: int | None = None
    commits: int | None = None
    agent_commits: int | None = None


@dataclass(frozen=True, slots=True)
class _ProjectStatsLanguage:
    name: str
    files: int
    lines: int


@dataclass(frozen=True, slots=True)
class _ProjectStatsCode:
    counter: str = "nonblank"
    code_files: int | None = None
    code_lines: int | None = None
    test_lines: int | None = None
    test_share: float | None = None
    doc_files: int | None = None
    doc_lines: int | None = None
    agent_context_files: int | None = None
    agent_context_lines: int | None = None
    languages: tuple[_ProjectStatsLanguage, ...] | None = None
    repos_configured: int = 0
    repos_measured: int = 0


@dataclass(frozen=True, slots=True)
class _ProjectStatsRuns:
    runs: int = 0
    completed: int = 0
    failed: int = 0
    other_terminal: int = 0
    in_progress: int = 0
    waiting: int = 0
    success_rate: float | None = None
    total_runtime_seconds: float = 0.0
    distinct_patches: int = 0
    unattributed_runs: int = 0
    last_run_ts: int | None = None


@dataclass(frozen=True, slots=True)
class ProjectStatsPatch:
    name: str
    status: str
    has_pr: bool = False
    runs: int = 0
    completed: int = 0
    failed: int = 0
    run_commits: int = 0
    total_runtime_seconds: int = 0
    first_run_ts: int | None = None
    last_run_ts: int | None = None


@dataclass(frozen=True, slots=True)
class _ProjectStatsRef:
    name: str
    commit: str
    shallow: bool = False
    fetched_at: int | None = None


@dataclass(frozen=True, slots=True)
class _ProjectStatsRoleCount:
    role: str
    files: int
    lines: int


@dataclass(frozen=True, slots=True)
class _ProjectStatsExclusionReason:
    reason: str
    files: int


@dataclass(frozen=True, slots=True)
class _ProjectStatsExclusionCount:
    exclusion: str
    files: int
    reasons: tuple[_ProjectStatsExclusionReason, ...] = ()


@dataclass(frozen=True, slots=True)
class _ProjectStatsSnapshot:
    tracked_files: int | None = None
    tracked_lines: int | None = None
    test_files: int | None = None
    test_lines: int | None = None
    doc_files: int | None = None
    doc_lines: int | None = None
    agent_context_files: int | None = None
    agent_context_lines: int | None = None
    lifetime_commits: int | None = None
    lifetime_agent_commits: int | None = None
    languages: tuple[_ProjectStatsLanguage, ...] | None = None
    as_of_ts: int | None = None
    counter: str | None = None
    role_counts: tuple[_ProjectStatsRoleCount, ...] | None = None
    exclusion_counts: tuple[_ProjectStatsExclusionCount, ...] | None = None
    skipped_symlinks: int | None = None
    skipped_gitlinks: int | None = None
    first_commit_ts: int | None = None
    last_commit_ts: int | None = None


@dataclass(frozen=True, slots=True)
class ProjectStatsRepo:
    id: str
    name: str
    kind: str
    tier: str
    status: str
    issue: ProjectStatsIssue | None = None
    ref: _ProjectStatsRef | None = None
    output: _ProjectStatsOutput | None = None
    lifetime: _ProjectStatsLifetime | None = None
    snapshot: _ProjectStatsSnapshot | None = None


@dataclass(frozen=True, slots=True)
class _ProjectStatsNotCounted:
    name: str
    reason: str


@dataclass(frozen=True, slots=True)
class ProjectStatsProject:
    key: str
    label: str
    state: str
    output: _ProjectStatsOutput | None = None
    lifetime: _ProjectStatsLifetime | None = None
    code: _ProjectStatsCode | None = None
    runs: _ProjectStatsRuns | None = None
    repos: tuple[ProjectStatsRepo, ...] = ()
    not_counted: tuple[_ProjectStatsNotCounted, ...] = ()
    models: tuple[ProjectStatsModel, ...] = ()
    patches: tuple[ProjectStatsPatch, ...] = ()
    truncated_patch_rows: int = 0
    coverage: ProjectStatsCoverage = ProjectStatsCoverage()


@dataclass(frozen=True, slots=True)
class ProjectStatsPortfolio:
    output: _ProjectStatsOutput | None = None
    lifetime: _ProjectStatsLifetime | None = None
    code: _ProjectStatsCode | None = None
    runs: _ProjectStatsRuns | None = None
    models: tuple[ProjectStatsModel, ...] = ()
    coverage: ProjectStatsCoverage = ProjectStatsCoverage()
