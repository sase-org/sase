"""Immutable, presentation-ready models for the Statistics views."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import cast

from sase.core.time import get_timezone
from sase.stats.query import RuntimeGroupBy

Payload = Mapping[str, object]


@dataclass(frozen=True, slots=True)
class _CountRow:
    """A labeled exact count, optionally with a zero-to-one share."""

    label: str
    count: int
    share: float | None = None


@dataclass(frozen=True, slots=True)
class _ActivityRow:
    """A durable activity count and its contributing-agent count."""

    label: str
    count: int
    distinct_agents: int


@dataclass(frozen=True, slots=True)
class _DistributionRow:
    """One labeled discrete-distribution bar."""

    label: str
    count: int


@dataclass(frozen=True, slots=True)
class _RunBucket:
    """One exact launch-time bucket used by Overview."""

    start_ts: int
    label: str
    runs: int


@dataclass(frozen=True, slots=True)
class _WorkspaceRow:
    project: str
    workspace_num: int
    runs: int


@dataclass(frozen=True, slots=True)
class _ProviderRow:
    provider: str
    model: str
    effort: str
    runs: int
    share: float
    success_rate: float
    mean_runtime_seconds: float | None


@dataclass(frozen=True, slots=True)
class _RuntimeRow:
    group: str
    runs: int
    total_seconds: float
    mean_seconds: float
    p50_seconds: float
    p95_seconds: float
    max_seconds: float
    share: float


@dataclass(frozen=True, slots=True)
class _OverviewView:
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
    buckets: tuple[_RunBucket, ...]
    top_providers: tuple[_CountRow, ...]
    top_skills: tuple[_ActivityRow, ...]


@dataclass(frozen=True, slots=True)
class _RunsView:
    outcomes: tuple[_CountRow, ...]
    in_progress: int
    waiting: int
    retry_chains: int
    retry_attempts: int
    retry_kills: int
    commits: int
    committing_agents: int
    average_commits_per_committing_agent: float
    commit_distribution: tuple[_DistributionRow, ...]
    top_repos: tuple[_CountRow, ...]


@dataclass(frozen=True, slots=True)
class _ProvidersView:
    rows: tuple[_ProviderRow, ...]


@dataclass(frozen=True, slots=True)
class _RuntimeView:
    group_by: RuntimeGroupBy
    rows: tuple[_RuntimeRow, ...]
    in_progress: int


@dataclass(frozen=True, slots=True)
class _ActivityView:
    skills: tuple[_ActivityRow, ...]
    memories: tuple[_ActivityRow, ...]
    workspaces: tuple[_WorkspaceRow, ...]


@dataclass(frozen=True, slots=True)
class _PlansQuestionsView:
    plans_proposed: int
    plan_tiers: tuple[_CountRow, ...]
    plans_approved: int
    plans_rejected: int
    plans_pending: int
    phases_per_epic: tuple[_DistributionRow, ...]
    mean_phases_per_epic: float
    question_sessions: int
    asking_agents: int
    questions: int
    questions_per_session: tuple[_DistributionRow, ...]
    mean_questions_per_session: float


@dataclass(frozen=True, slots=True)
class StatisticsViews:
    """All six views built from one run and one activity response."""

    start_ts: int
    end_ts: int
    empty: bool
    overview: _OverviewView
    runs: _RunsView
    providers: _ProvidersView
    runtime: _RuntimeView
    activity: _ActivityView
    plans_questions: _PlansQuestionsView


def build_statistics_views(
    run_payload: Payload,
    activity_payload: Payload,
    *,
    previous_run_payload: Payload | None = None,
    timezone: tzinfo | None = None,
) -> StatisticsViews:
    """Build every Statistics view without performing I/O."""
    totals = _mapping(run_payload.get("totals"))
    activity = _build_activity_view(run_payload, activity_payload)
    plans_questions = _build_plans_questions_view(run_payload, activity_payload)
    return StatisticsViews(
        start_ts=_integer(run_payload.get("start_ts")),
        end_ts=_integer(run_payload.get("end_ts")),
        empty=(
            _integer(totals.get("runs")) == 0
            and not _has_durable_activity(activity, plans_questions)
        ),
        overview=_build_overview_view(
            run_payload,
            activity_payload,
            previous_run_payload=previous_run_payload,
            timezone=timezone,
        ),
        runs=_build_runs_view(run_payload),
        providers=_build_providers_view(run_payload),
        runtime=_build_runtime_view(run_payload),
        activity=activity,
        plans_questions=plans_questions,
    )


def _build_overview_view(
    run_payload: Payload,
    activity_payload: Payload,
    *,
    previous_run_payload: Payload | None = None,
    timezone: tzinfo | None = None,
) -> _OverviewView:
    totals = _mapping(run_payload.get("totals"))
    commits = _mapping(run_payload.get("commits"))
    plans = _mapping(activity_payload.get("plans"))
    questions = _mapping(activity_payload.get("questions"))
    current_runs = _integer(totals.get("runs"))
    terminal_runs = sum(
        _integer(row.get("count")) for row in _rows(run_payload, "outcomes")
    )

    previous_runs: int | None = None
    if previous_run_payload is not None:
        previous_runs = _integer(
            _mapping(previous_run_payload.get("totals")).get("runs")
        )
    delta = None if previous_runs is None else current_runs - previous_runs
    delta_ratio = _delta_ratio(current_runs, previous_runs)

    tier_counts = _count_map(_rows(plans, "tiers"))
    provider_counts: defaultdict[str, int] = defaultdict(int)
    for row in _rows(run_payload, "providers"):
        provider_counts[_text(row.get("provider"), "unknown")] += _integer(
            row.get("runs")
        )
    providers = tuple(
        _CountRow(label, count, _ratio(count, current_runs))
        for label, count in sorted(
            provider_counts.items(), key=lambda item: (-item[1], item[0])
        )[:5]
    )

    bucket_seconds = _integer(run_payload.get("bucket_seconds"), 86_400)
    resolved_timezone = timezone or get_timezone()
    return _OverviewView(
        agents_run=current_runs,
        completed=_integer(totals.get("completed")),
        failed=_integer(totals.get("failed")),
        runs_delta=delta,
        runs_delta_ratio=delta_ratio,
        success_rate=_ratio(_integer(totals.get("completed")), terminal_runs),
        commits=_integer(commits.get("total_commits")),
        committing_agents=_integer(commits.get("committing_agents")),
        plans_proposed=_integer(plans.get("proposed")),
        epic_plans=tier_counts.get("epic", 0),
        tale_plans=tier_counts.get("tale", 0),
        question_sessions=_integer(questions.get("sessions")),
        questions=_integer(questions.get("questions")),
        buckets=tuple(
            _RunBucket(
                start_ts=_integer(row.get("start_ts")),
                label=_bucket_label(
                    _integer(row.get("start_ts")), bucket_seconds, resolved_timezone
                ),
                runs=_integer(row.get("runs")),
            )
            for row in _rows(run_payload, "buckets")
        ),
        top_providers=providers,
        top_skills=_activity_rows(_rows(activity_payload, "skills")),
    )


def _build_runs_view(run_payload: Payload) -> _RunsView:
    totals = _mapping(run_payload.get("totals"))
    retries = _mapping(run_payload.get("retries"))
    commits = _mapping(run_payload.get("commits"))
    outcome_rows = _rows(run_payload, "outcomes")
    terminal_runs = sum(_integer(row.get("count")) for row in outcome_rows)
    distribution = _mapping(commits.get("distribution"))
    return _RunsView(
        outcomes=tuple(
            _CountRow(
                _text(row.get("name"), "unknown"),
                _integer(row.get("count")),
                _ratio(_integer(row.get("count")), terminal_runs),
            )
            for row in outcome_rows
        ),
        in_progress=_integer(totals.get("in_progress")),
        waiting=_integer(totals.get("waiting")),
        retry_chains=_integer(retries.get("chains")),
        retry_attempts=_integer(retries.get("attempts")),
        retry_kills=_integer(retries.get("kills")),
        commits=_integer(commits.get("total_commits")),
        committing_agents=_integer(commits.get("committing_agents")),
        average_commits_per_committing_agent=_number(
            commits.get("average_per_committing_agent")
        ),
        commit_distribution=tuple(
            _DistributionRow(label, _integer(distribution.get(key)))
            for key, label in (
                ("zero", "0"),
                ("one", "1"),
                ("two", "2"),
                ("three_plus", "3+"),
            )
        ),
        top_repos=_count_rows(_rows(commits, "top_repos")),
    )


def _build_providers_view(run_payload: Payload) -> _ProvidersView:
    total_runs = _integer(_mapping(run_payload.get("totals")).get("runs"))
    return _ProvidersView(
        rows=tuple(
            _ProviderRow(
                provider=_text(row.get("provider"), "unknown"),
                model=_text(row.get("model"), "unknown"),
                effort=_text(row.get("effort"), "default"),
                runs=_integer(row.get("runs")),
                share=_ratio(_integer(row.get("runs")), total_runs),
                success_rate=_number(row.get("success_rate")),
                mean_runtime_seconds=_optional_number(row.get("mean_runtime_seconds")),
            )
            for row in _rows(run_payload, "providers")
        )
    )


def _build_runtime_view(run_payload: Payload) -> _RuntimeView:
    totals = _mapping(run_payload.get("totals"))
    rows = _rows(run_payload, "runtime_groups")
    total_seconds = sum(_number(row.get("total_seconds")) for row in rows)
    raw_group = _text(run_payload.get("runtime_group_by"), "agent")
    valid_groups = {"tribe", "clan", "family", "agent", "provider", "model", "workflow"}
    group_by = cast(RuntimeGroupBy, raw_group if raw_group in valid_groups else "agent")
    return _RuntimeView(
        group_by=group_by,
        rows=tuple(
            _RuntimeRow(
                group=_text(row.get("group"), "unknown"),
                runs=_integer(row.get("runs")),
                total_seconds=_number(row.get("total_seconds")),
                mean_seconds=_number(row.get("mean_seconds")),
                p50_seconds=_number(row.get("p50_seconds")),
                p95_seconds=_number(row.get("p95_seconds")),
                max_seconds=_number(row.get("max_seconds")),
                share=_ratio(_number(row.get("total_seconds")), total_seconds),
            )
            for row in rows
        ),
        in_progress=_integer(totals.get("in_progress")),
    )


def _build_activity_view(
    run_payload: Payload, activity_payload: Payload
) -> _ActivityView:
    return _ActivityView(
        skills=_activity_rows(_rows(activity_payload, "skills")),
        memories=_activity_rows(_rows(activity_payload, "memories")),
        workspaces=tuple(
            _WorkspaceRow(
                project=_text(row.get("project"), "unknown"),
                workspace_num=_integer(row.get("workspace_num")),
                runs=_integer(row.get("runs")),
            )
            for row in _rows(run_payload, "workspaces")
        ),
    )


def _build_plans_questions_view(
    run_payload: Payload, activity_payload: Payload
) -> _PlansQuestionsView:
    plans = _mapping(activity_payload.get("plans"))
    questions = _mapping(activity_payload.get("questions"))
    run_questions = _mapping(run_payload.get("questions"))
    return _PlansQuestionsView(
        plans_proposed=_integer(plans.get("proposed")),
        plan_tiers=_count_rows(_rows(plans, "tiers")),
        plans_approved=_integer(plans.get("approved")),
        plans_rejected=_integer(plans.get("rejected")),
        plans_pending=_integer(plans.get("pending")),
        phases_per_epic=_distribution_rows(_rows(plans, "phases_per_epic")),
        mean_phases_per_epic=_number(plans.get("mean_phases_per_epic")),
        question_sessions=_integer(questions.get("sessions")),
        asking_agents=_integer(run_questions.get("asking_agents")),
        questions=_integer(questions.get("questions")),
        questions_per_session=_distribution_rows(
            _rows(questions, "questions_per_session")
        ),
        mean_questions_per_session=_number(questions.get("mean_questions_per_session")),
    )


def _has_durable_activity(
    activity: _ActivityView,
    plans_questions: _PlansQuestionsView,
) -> bool:
    return bool(
        activity.skills
        or activity.memories
        or activity.workspaces
        or plans_questions.plans_proposed
        or plans_questions.plan_tiers
        or plans_questions.plans_approved
        or plans_questions.plans_rejected
        or plans_questions.plans_pending
        or plans_questions.phases_per_epic
        or plans_questions.question_sessions
        or plans_questions.asking_agents
        or plans_questions.questions
        or plans_questions.questions_per_session
    )


def _rows(payload: Payload, key: str) -> tuple[Payload, ...]:
    value = payload.get(key)
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _mapping(value: object) -> Payload:
    return value if isinstance(value, Mapping) else {}


def _count_map(rows: tuple[Payload, ...]) -> dict[str, int]:
    return {_text(row.get("name")): _integer(row.get("count")) for row in rows}


def _count_rows(rows: tuple[Payload, ...]) -> tuple[_CountRow, ...]:
    return tuple(
        _CountRow(_text(row.get("name"), "unknown"), _integer(row.get("count")))
        for row in rows
    )


def _activity_rows(rows: tuple[Payload, ...]) -> tuple[_ActivityRow, ...]:
    return tuple(
        _ActivityRow(
            _text(row.get("name"), "unknown"),
            _integer(row.get("count")),
            _integer(row.get("distinct_agents")),
        )
        for row in rows
    )


def _distribution_rows(rows: tuple[Payload, ...]) -> tuple[_DistributionRow, ...]:
    return tuple(
        _DistributionRow(str(_integer(row.get("value"))), _integer(row.get("count")))
        for row in rows
    )


def _integer(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    return int(value) if isinstance(value, (int, float)) else default


def _number(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    return float(value) if isinstance(value, (int, float)) else default


def _optional_number(value: object) -> float | None:
    return (
        _number(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else None
    )


def _text(value: object, default: str = "") -> str:
    return value if isinstance(value, str) and value else default


def _ratio(numerator: int | float, denominator: int | float) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def _delta_ratio(current: int, previous: int | None) -> float | None:
    if previous is None:
        return None
    if previous == 0:
        return 0.0 if current == 0 else None
    return (current - previous) / previous


def _bucket_label(start_ts: int, bucket_seconds: int, timezone: tzinfo) -> str:
    value = datetime.fromtimestamp(start_ts, timezone)
    return value.strftime("%a %H:%M" if bucket_seconds < 86_400 else "%b %d")


__all__ = [
    "StatisticsViews",
    "build_statistics_views",
]
