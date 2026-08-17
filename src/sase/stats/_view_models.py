"""Immutable, presentation-ready models for individual Statistics views."""

from __future__ import annotations

from dataclasses import dataclass

from sase.stats.perf_query import PerfGroupBy
from sase.stats.query import RuntimeGroupBy
from sase.stats.ranges import StatsRange
from sase.telemetry.render.palette import Status


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
class PatchWorkRow:
    project_key: str
    project_label: str
    patch_key: str
    patch_label: str
    status: str
    has_pr: bool
    runs: int
    distinct_agents: int
    commits: int
    total_runtime_seconds: float
    first_run_ts: float
    last_run_ts: float

    @property
    def changespec_key(self) -> str:  # legacy stats view alias
        return self.patch_key

    @property
    def changespec_label(self) -> str:  # legacy stats view alias
        return self.patch_label


ChangeSpecWorkRow = PatchWorkRow  # legacy stats view alias


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
    distinct_patches: int
    unattributed_runs: int
    total_runtime_seconds: float
    last_run_ts: float
    patches: tuple[PatchWorkRow, ...]

    @property
    def distinct_changespecs(self) -> int:  # legacy stats view alias
        return self.distinct_patches

    @property
    def changespecs(self) -> tuple[PatchWorkRow, ...]:  # legacy stats view alias
        return self.patches


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
    bucket_group_seconds: int | None
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
    patches: tuple[PatchWorkRow, ...]
    project_count: int
    patch_count: int
    unattributed_runs: int
    truncated_patch_rows: int
    malformed_spec_files_skipped: int

    @property
    def changespecs(self) -> tuple[PatchWorkRow, ...]:  # legacy stats view alias
        return self.patches

    @property
    def changespec_count(self) -> int:  # legacy stats view alias
        return self.patch_count

    @property
    def truncated_changespec_rows(self) -> int:  # legacy stats view alias
        return self.truncated_patch_rows


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

    @property
    def empty(self) -> bool:
        """True when no skill, memory, or workspace rows were recorded."""
        return not (self.skills or self.memories or self.workspaces)


@dataclass(frozen=True, slots=True)
class XPromptCountRow:
    """One xprompt cross-tab count and its within-xprompt share."""

    key: str
    label: str
    count: int
    share: float


@dataclass(frozen=True, slots=True)
class XPromptRow:
    """One ranked launch-boundary xprompt usage row."""

    name: str
    kind: str
    tags: tuple[str, ...]
    runs: int
    references: int
    distinct_agents: int
    completed: int
    failed: int
    success_rate: float
    total_runtime_seconds: float
    mean_runtime_seconds: float | None
    first_run_ts: float
    last_run_ts: float
    share: float
    models: tuple[XPromptCountRow, ...]
    projects: tuple[XPromptCountRow, ...]
    partners: tuple[XPromptCountRow, ...]


@dataclass(frozen=True, slots=True)
class XPromptFocusView:
    """Full breakdown for one exact xprompt focus."""

    name: str
    found: bool
    kind: str
    tags: tuple[str, ...]
    runs: int
    references: int
    distinct_agents: int
    completed: int
    failed: int
    success_rate: float
    total_runtime_seconds: float
    mean_runtime_seconds: float | None
    first_run_ts: float
    last_run_ts: float
    models: tuple[XPromptCountRow, ...]
    projects: tuple[XPromptCountRow, ...]
    partners: tuple[XPromptCountRow, ...]
    providers: tuple[XPromptCountRow, ...]
    tribes: tuple[XPromptCountRow, ...]
    buckets: tuple[RunBucket, ...]


@dataclass(frozen=True, slots=True)
class XPromptsView:
    """Launch-boundary xprompt usage for the selected Statistics scope."""

    available: bool
    runs_with_xprompts: int
    runs_without_xprompts: int
    distinct_xprompts: int
    total_references: int
    truncated_rows: int
    rows: tuple[XPromptRow, ...]
    focus: XPromptFocusView | None


@dataclass(frozen=True, slots=True)
class PlansQuestionsView:
    plans_proposed: int
    plan_tiers: tuple[CountRow, ...]
    plans_approved: int
    plans_rejected: int
    plans_feedback: int
    plans_pending: int
    phases_per_epic: tuple[DistributionRow, ...]
    mean_phases_per_epic: float
    question_sessions: int
    asking_agents: int
    questions: int
    questions_per_session: tuple[DistributionRow, ...]
    mean_questions_per_session: float
    coverage_start_ts: float | None

    @property
    def empty(self) -> bool:
        """True when no plan or question activity was recorded."""
        return (
            self.plans_proposed == 0
            and self.plans_approved == 0
            and self.plans_rejected == 0
            and self.plans_feedback == 0
            and self.plans_pending == 0
            and self.question_sessions == 0
            and self.questions == 0
        )


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
    lanes_counted: int
    lanes_without_end_skipped: int
    user_hidden_skipped: int
    malformed_rows_skipped: int
    invalid_intervals_skipped: int


@dataclass(frozen=True, slots=True)
class PerfHeroTile:
    """One hero tile: graded value, optional delta, and a secondary detail line."""

    key: str
    caption: str
    available: bool
    value: float | None
    status: Status | None
    delta_ratio: float | None
    lower_is_better: bool
    sparkline: tuple[float, ...]
    detail: str
    sample_count: int


@dataclass(frozen=True, slots=True)
class PerfStartupStageRow:
    stage: str
    label: str
    p50: float | None
    p95: float | None
    max: float | None
    samples: int


@dataclass(frozen=True, slots=True)
class PerfSlowestSession:
    ts: float
    visible_ready_seconds: float
    initial_tab: str | None


@dataclass(frozen=True, slots=True)
class PerfStartupSection:
    available: bool
    sessions: int
    stages: tuple[PerfStartupStageRow, ...]
    sparkline: tuple[float, ...]
    slowest: PerfSlowestSession | None
    tile: PerfHeroTile


@dataclass(frozen=True, slots=True)
class PerfStallEventRow:
    event: str
    count: int
    worst_seconds: float | None
    median_seconds: float | None
    last_seen_ts: float | None
    suppressed_count: int


@dataclass(frozen=True, slots=True)
class PerfStallContextRow:
    name: str
    count: int


@dataclass(frozen=True, slots=True)
class PerfStallsSection:
    available: bool
    stall_count: int
    hitch_count: int
    worst_seconds: float | None
    recovery_count: int
    events: tuple[PerfStallEventRow, ...]
    top_contexts: tuple[PerfStallContextRow, ...]
    tile: PerfHeroTile


@dataclass(frozen=True, slots=True)
class PerfLaunchStage:
    ts: float
    stage: str
    elapsed_ms: float
    operation: str | None
    slow_stage: bool


@dataclass(frozen=True, slots=True)
class PerfLaunchesSection:
    available: bool
    count: int
    p50_ms: float | None
    p95_ms: float | None
    max_ms: float | None
    slow_stage_count: int
    worst_stages: tuple[PerfLaunchStage, ...]
    tile: PerfHeroTile


@dataclass(frozen=True, slots=True)
class PerfLatencyRow:
    key: str
    label: str
    p50: float | None
    p95: float | None
    max: float | None
    count: int
    error_rate: float | None
    retry_rate: float | None
    share: float
    tokens_in: int | None
    tokens_out: int | None
    cache_read_tokens: int | None
    cache_read_share: float | None
    status: Status | None


@dataclass(frozen=True, slots=True)
class PerfLatencySection:
    available: bool
    group_by: PerfGroupBy
    rows: tuple[PerfLatencyRow, ...]
    agent_tile: PerfHeroTile
    llm_tile: PerfHeroTile


@dataclass(frozen=True, slots=True)
class PerfLogCoverage:
    source: str
    path: str
    present: bool
    records_scanned: int
    records_in_window: int
    earliest_ts: float | None
    latest_ts: float | None
    truncated: bool
    malformed_skipped: int


@dataclass(frozen=True, slots=True)
class PerfTelemetryCoverage:
    enabled: bool
    available: bool
    store_path: str
    store_size_bytes: int
    raw_sample_count: int
    rollup_5m_count: int
    rollup_1h_count: int
    resolution: str | None
    last_write_ts: int | None
    last_write_age_seconds: float | None
    last_write_by_subsystem: tuple[tuple[str, int], ...]
    earliest_sample_ts: int | None
    latest_sample_ts: int | None
    error: str | None


@dataclass(frozen=True, slots=True)
class PerfProbeStatus:
    name: str
    enabled: bool
    hint: str


@dataclass(frozen=True, slots=True)
class PerfCoverage:
    telemetry: PerfTelemetryCoverage
    logs: tuple[PerfLogCoverage, ...]
    probes: tuple[PerfProbeStatus, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PerfView:
    """Presentation-ready Perf snapshot. Every section carries ``available``."""

    available: bool
    selected_range: StatsRange
    group_by: PerfGroupBy
    startup: PerfStartupSection
    stalls: PerfStallsSection
    launches: PerfLaunchesSection
    latency: PerfLatencySection
    coverage: PerfCoverage
    tiles: tuple[PerfHeroTile, ...]
