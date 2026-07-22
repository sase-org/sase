"""Immutable, presentation-ready models for individual Statistics views."""

from __future__ import annotations

from dataclasses import dataclass

from sase.stats.query import RuntimeGroupBy


@dataclass(frozen=True, slots=True)
class CountRow:
    """A labeled exact count, optionally with a zero-to-one share."""

    label: str
    count: int
    share: float | None = None


@dataclass(frozen=True, slots=True)
class ActivityRow:
    """A durable activity count and its contributing-agent count."""

    label: str
    count: int
    distinct_agents: int


@dataclass(frozen=True, slots=True)
class DistributionRow:
    """One labeled discrete-distribution bar."""

    label: str
    count: int


@dataclass(frozen=True, slots=True)
class RunBucket:
    """One exact launch-time bucket used by Overview."""

    start_ts: int
    label: str
    runs: int


@dataclass(frozen=True, slots=True)
class WorkspaceRow:
    project_key: str
    project_label: str
    workspace_num: int
    runs: int


@dataclass(frozen=True, slots=True)
class ProviderRow:
    provider: str
    model: str
    effort: str
    runs: int
    share: float
    success_rate: float
    mean_runtime_seconds: float | None


@dataclass(frozen=True, slots=True)
class RuntimeRow:
    group_key: str
    group_label: str
    runs: int
    total_seconds: float
    mean_seconds: float
    p50_seconds: float
    p95_seconds: float
    max_seconds: float
    share: float


@dataclass(frozen=True, slots=True)
class ChangeSpecWorkRow:
    project_key: str
    project_label: str
    changespec_key: str
    changespec_label: str
    status: str
    has_pr: bool
    runs: int
    distinct_agents: int
    commits: int
    total_runtime_seconds: float
    first_run_ts: float
    last_run_ts: float


@dataclass(frozen=True, slots=True)
class ProjectWorkRow:
    project_key: str
    project_label: str
    runs: int
    completed: int
    failed: int
    other_terminal: int
    in_progress: int
    waiting: int
    success_rate: float
    commits: int
    distinct_changespecs: int
    unattributed_runs: int
    total_runtime_seconds: float
    last_run_ts: float
    changespecs: tuple[ChangeSpecWorkRow, ...]


@dataclass(frozen=True, slots=True)
class OverviewView:
    agents_run: int
    completed: int
    failed: int
    runs_delta: int | None
    runs_delta_ratio: float | None
    success_rate: float
    commits: int
    committing_agents: int
    plans_proposed: int
    epic_plans: int
    tale_plans: int
    question_sessions: int
    questions: int
    buckets: tuple[RunBucket, ...]
    top_providers: tuple[CountRow, ...]
    top_skills: tuple[ActivityRow, ...]
    top_projects: tuple[ProjectWorkRow, ...]


@dataclass(frozen=True, slots=True)
class RunsView:
    outcomes: tuple[CountRow, ...]
    in_progress: int
    waiting: int
    retry_chains: int
    retry_attempts: int
    retry_kills: int
    commits: int
    committing_agents: int
    average_commits_per_committing_agent: float
    commit_distribution: tuple[DistributionRow, ...]
    top_repos: tuple[CountRow, ...]


@dataclass(frozen=True, slots=True)
class ProjectsView:
    projects: tuple[ProjectWorkRow, ...]
    changespecs: tuple[ChangeSpecWorkRow, ...]
    project_count: int
    changespec_count: int
    unattributed_runs: int
    truncated_changespec_rows: int
    malformed_spec_files_skipped: int


@dataclass(frozen=True, slots=True)
class ProvidersView:
    rows: tuple[ProviderRow, ...]


@dataclass(frozen=True, slots=True)
class RuntimeView:
    group_by: RuntimeGroupBy
    rows: tuple[RuntimeRow, ...]
    in_progress: int


@dataclass(frozen=True, slots=True)
class ActivityView:
    skills: tuple[ActivityRow, ...]
    memories: tuple[ActivityRow, ...]
    workspaces: tuple[WorkspaceRow, ...]


@dataclass(frozen=True, slots=True)
class PlansQuestionsView:
    plans_proposed: int
    plan_tiers: tuple[CountRow, ...]
    plans_approved: int
    plans_rejected: int
    plans_pending: int
    phases_per_epic: tuple[DistributionRow, ...]
    mean_phases_per_epic: float
    question_sessions: int
    asking_agents: int
    questions: int
    questions_per_session: tuple[DistributionRow, ...]
    mean_questions_per_session: float


@dataclass(frozen=True, slots=True)
class RunnerOccupancyRow:
    """Exact wall-clock time and share observed at one runner count."""

    runners: int
    seconds: float
    share: float


@dataclass(frozen=True, slots=True)
class RunnerTrendSlice:
    """One bounded, contiguous slice of the runner-occupancy trend."""

    start_ts: float
    end_ts: float
    label: str
    average_runners: float
    peak_runners: int
    busy_seconds: float
    runner_seconds: float


@dataclass(frozen=True, slots=True)
class RunnersView:
    """Historical runner-slot occupancy over one effective analysis window.

    ``available`` distinguishes a present payload (even a wholly idle fixed
    window that renders an honest zero-runner distribution) from an absent one
    (an all-time request with no recorded runner coverage, or an older/partial
    payload). ``current_limit`` carries the current global ``max_running_agents``
    reference captured off-thread, never a historical saturation value.
    """

    available: bool
    start_ts: float
    end_ts: float
    peak_runners: int
    peak_seconds: float
    average_runners: float
    busy_seconds: float
    busy_share: float
    runner_seconds: float
    current_limit: int | None
    distribution: tuple[RunnerOccupancyRow, ...]
    trend: tuple[RunnerTrendSlice, ...]
    malformed_rows_skipped: int
    invalid_intervals_skipped: int
