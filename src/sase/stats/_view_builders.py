"""Builders for the non-runner Statistics views."""

from __future__ import annotations

from collections import defaultdict
from datetime import tzinfo
from typing import cast

from sase.project_display_names import (
    ProjectDisplaySnapshot,
    humanize_cl_name,
    project_display_for,
)
from sase.stats._view_models import (
    ActivityView,
    ChangeSpecWorkRow,
    CountRow,
    DistributionRow,
    OverviewView,
    PlansQuestionsView,
    ProjectWorkRow,
    ProjectsView,
    ProviderRow,
    ProvidersView,
    RunBucket,
    RunsView,
    RuntimeRow,
    RuntimeView,
    WorkspaceRow,
)
from sase.stats._view_payload import (
    Payload,
    activity_rows,
    boolean,
    bucket_label,
    count_map,
    count_rows,
    delta_ratio,
    distribution_rows,
    integer,
    mapping,
    number,
    optional_number,
    ratio,
    rows,
    text,
)
from sase.stats.query import RuntimeGroupBy


def build_overview_view(
    run_payload: Payload,
    activity_payload: Payload,
    *,
    previous_run_payload: Payload | None = None,
    timezone: tzinfo,
    projects: ProjectsView,
) -> OverviewView:
    totals = mapping(run_payload.get("totals"))
    commits = mapping(run_payload.get("commits"))
    plans = mapping(activity_payload.get("plans"))
    questions = mapping(activity_payload.get("questions"))
    current_runs = integer(totals.get("runs"))
    terminal_runs = sum(
        integer(row.get("count")) for row in rows(run_payload, "outcomes")
    )

    previous_runs: int | None = None
    if previous_run_payload is not None:
        previous_runs = integer(mapping(previous_run_payload.get("totals")).get("runs"))
    delta = None if previous_runs is None else current_runs - previous_runs
    runs_delta_ratio = delta_ratio(current_runs, previous_runs)

    tier_counts = count_map(rows(plans, "tiers"))
    provider_counts: defaultdict[str, int] = defaultdict(int)
    for row in rows(run_payload, "providers"):
        provider_counts[text(row.get("provider"), "unknown")] += integer(
            row.get("runs")
        )
    providers = tuple(
        CountRow(label, count, ratio(count, current_runs))
        for label, count in sorted(
            provider_counts.items(), key=lambda item: (-item[1], item[0])
        )[:5]
    )

    bucket_seconds = integer(run_payload.get("bucket_seconds"), 86_400)
    return OverviewView(
        agents_run=current_runs,
        completed=integer(totals.get("completed")),
        failed=integer(totals.get("failed")),
        runs_delta=delta,
        runs_delta_ratio=runs_delta_ratio,
        success_rate=ratio(integer(totals.get("completed")), terminal_runs),
        commits=integer(commits.get("total_commits")),
        committing_agents=integer(commits.get("committing_agents")),
        plans_proposed=integer(plans.get("proposed")),
        epic_plans=tier_counts.get("epic", 0),
        tale_plans=tier_counts.get("tale", 0),
        question_sessions=integer(questions.get("sessions")),
        questions=integer(questions.get("questions")),
        buckets=tuple(
            RunBucket(
                start_ts=integer(row.get("start_ts")),
                label=bucket_label(
                    integer(row.get("start_ts")), bucket_seconds, timezone
                ),
                runs=integer(row.get("runs")),
            )
            for row in rows(run_payload, "buckets")
        ),
        top_providers=providers,
        top_skills=activity_rows(rows(activity_payload, "skills")),
        top_projects=projects.projects[:5],
    )


def build_runs_view(run_payload: Payload) -> RunsView:
    totals = mapping(run_payload.get("totals"))
    retries = mapping(run_payload.get("retries"))
    commits = mapping(run_payload.get("commits"))
    outcome_rows = rows(run_payload, "outcomes")
    terminal_runs = sum(integer(row.get("count")) for row in outcome_rows)
    distribution = mapping(commits.get("distribution"))
    return RunsView(
        outcomes=tuple(
            CountRow(
                text(row.get("name"), "unknown"),
                integer(row.get("count")),
                ratio(integer(row.get("count")), terminal_runs),
            )
            for row in outcome_rows
        ),
        in_progress=integer(totals.get("in_progress")),
        waiting=integer(totals.get("waiting")),
        retry_chains=integer(retries.get("chains")),
        retry_attempts=integer(retries.get("attempts")),
        retry_kills=integer(retries.get("kills")),
        commits=integer(commits.get("total_commits")),
        committing_agents=integer(commits.get("committing_agents")),
        average_commits_per_committing_agent=number(
            commits.get("average_per_committing_agent")
        ),
        commit_distribution=tuple(
            DistributionRow(label, integer(distribution.get(key)))
            for key, label in (
                ("zero", "0"),
                ("one", "1"),
                ("two", "2"),
                ("three_plus", "3+"),
            )
        ),
        top_repos=count_rows(rows(commits, "top_repos")),
    )


def build_projects_view(
    run_payload: Payload,
    display_snapshot: ProjectDisplaySnapshot,
) -> ProjectsView:
    work = mapping(run_payload.get("work"))
    changespec_rows: list[ChangeSpecWorkRow] = []
    for row in rows(work, "changespecs"):
        project = project_display_for(
            text(row.get("project"), "unknown"),
            snapshot=display_snapshot,
        )
        changespec_key = text(row.get("name"), "unknown")
        changespec_rows.append(
            ChangeSpecWorkRow(
                project_key=project.project_key,
                project_label=project.project_label,
                changespec_key=changespec_key,
                changespec_label=humanize_cl_name(
                    changespec_key,
                    snapshot=display_snapshot,
                ),
                status=text(row.get("status"), "unknown"),
                has_pr=boolean(row.get("has_pr")),
                runs=integer(row.get("runs")),
                distinct_agents=integer(row.get("distinct_agents")),
                commits=integer(row.get("commits")),
                total_runtime_seconds=number(row.get("total_runtime_seconds")),
                first_run_ts=number(row.get("first_run_ts")),
                last_run_ts=number(row.get("last_run_ts")),
            )
        )
    changespecs = tuple(changespec_rows)
    changespecs_by_project: defaultdict[str, list[ChangeSpecWorkRow]] = defaultdict(
        list
    )
    for changespec in changespecs:
        changespecs_by_project[changespec.project_key].append(changespec)

    project_rows: list[ProjectWorkRow] = []
    for row in rows(work, "projects"):
        project = project_display_for(
            text(row.get("project"), "unknown"),
            snapshot=display_snapshot,
        )
        project_rows.append(
            ProjectWorkRow(
                project_key=project.project_key,
                project_label=project.project_label,
                runs=integer(row.get("runs")),
                completed=integer(row.get("completed")),
                failed=integer(row.get("failed")),
                other_terminal=integer(row.get("other_terminal")),
                in_progress=integer(row.get("in_progress")),
                waiting=integer(row.get("waiting")),
                success_rate=number(row.get("success_rate")),
                commits=integer(row.get("commits")),
                distinct_changespecs=integer(row.get("distinct_changespecs")),
                unattributed_runs=integer(row.get("unattributed_runs")),
                total_runtime_seconds=number(row.get("total_runtime_seconds")),
                last_run_ts=number(row.get("last_run_ts")),
                changespecs=tuple(changespecs_by_project[project.project_key]),
            )
        )
    projects = tuple(
        sorted(
            project_rows,
            key=lambda item: (
                -item.runs,
                item.project_label.casefold(),
                item.project_key,
            ),
        )
    )
    truncated = integer(work.get("truncated_changespec_rows"))
    return ProjectsView(
        projects=projects,
        changespecs=changespecs,
        project_count=len(projects),
        changespec_count=len(changespecs) + truncated,
        unattributed_runs=integer(work.get("unattributed_runs")),
        truncated_changespec_rows=truncated,
        malformed_spec_files_skipped=integer(work.get("malformed_spec_files_skipped")),
    )


def build_providers_view(run_payload: Payload) -> ProvidersView:
    total_runs = integer(mapping(run_payload.get("totals")).get("runs"))
    return ProvidersView(
        rows=tuple(
            ProviderRow(
                provider=text(row.get("provider"), "unknown"),
                model=text(row.get("model"), "unknown"),
                effort=text(row.get("effort"), "default"),
                runs=integer(row.get("runs")),
                share=ratio(integer(row.get("runs")), total_runs),
                success_rate=number(row.get("success_rate")),
                mean_runtime_seconds=optional_number(row.get("mean_runtime_seconds")),
            )
            for row in rows(run_payload, "providers")
        )
    )


def build_runtime_view(
    run_payload: Payload,
    display_snapshot: ProjectDisplaySnapshot,
) -> RuntimeView:
    totals = mapping(run_payload.get("totals"))
    group_rows = rows(run_payload, "runtime_groups")
    total_seconds = sum(number(row.get("total_seconds")) for row in group_rows)
    raw_group = text(run_payload.get("runtime_group_by"), "agent")
    valid_groups = {
        "tribe",
        "clan",
        "family",
        "agent",
        "provider",
        "model",
        "workflow",
        "project",
        "changespec",
    }
    group_by = cast(RuntimeGroupBy, raw_group if raw_group in valid_groups else "agent")
    runtime_rows: list[RuntimeRow] = []
    for row in group_rows:
        group_key = text(row.get("group"), "unknown")
        if group_by == "project":
            group_label = project_display_for(
                group_key,
                snapshot=display_snapshot,
            ).project_label
        elif group_by == "changespec":
            group_label = humanize_cl_name(group_key, snapshot=display_snapshot)
        else:
            group_label = group_key
        runtime_rows.append(
            RuntimeRow(
                group_key=group_key,
                group_label=group_label,
                runs=integer(row.get("runs")),
                total_seconds=number(row.get("total_seconds")),
                mean_seconds=number(row.get("mean_seconds")),
                p50_seconds=number(row.get("p50_seconds")),
                p95_seconds=number(row.get("p95_seconds")),
                max_seconds=number(row.get("max_seconds")),
                share=ratio(number(row.get("total_seconds")), total_seconds),
            )
        )
    return RuntimeView(
        group_by=group_by,
        rows=tuple(runtime_rows),
        in_progress=integer(totals.get("in_progress")),
    )


def build_activity_view(
    run_payload: Payload,
    activity_payload: Payload,
    display_snapshot: ProjectDisplaySnapshot,
) -> ActivityView:
    workspace_rows: list[WorkspaceRow] = []
    for row in rows(run_payload, "workspaces"):
        project = project_display_for(
            text(row.get("project"), "unknown"),
            snapshot=display_snapshot,
        )
        workspace_rows.append(
            WorkspaceRow(
                project_key=project.project_key,
                project_label=project.project_label,
                workspace_num=integer(row.get("workspace_num")),
                runs=integer(row.get("runs")),
            )
        )
    return ActivityView(
        skills=activity_rows(rows(activity_payload, "skills")),
        memories=activity_rows(rows(activity_payload, "memories")),
        workspaces=tuple(workspace_rows),
    )


def build_plans_questions_view(
    run_payload: Payload, activity_payload: Payload
) -> PlansQuestionsView:
    run_plans = mapping(run_payload.get("plans"))
    activity_plans = mapping(activity_payload.get("plans"))
    questions = mapping(activity_payload.get("questions"))
    run_questions = mapping(run_payload.get("questions"))
    return PlansQuestionsView(
        plans_proposed=integer(run_plans.get("proposed")),
        plan_tiers=count_rows(rows(activity_plans, "tiers")),
        plans_approved=integer(run_plans.get("approved")),
        plans_rejected=integer(run_plans.get("rejected")),
        plans_pending=integer(run_plans.get("pending")),
        phases_per_epic=distribution_rows(rows(activity_plans, "phases_per_epic")),
        mean_phases_per_epic=number(activity_plans.get("mean_phases_per_epic")),
        question_sessions=integer(run_questions.get("sessions")),
        asking_agents=integer(run_questions.get("asking_agents")),
        questions=integer(questions.get("questions")),
        questions_per_session=distribution_rows(
            rows(questions, "questions_per_session")
        ),
        mean_questions_per_session=number(questions.get("mean_questions_per_session")),
    )
