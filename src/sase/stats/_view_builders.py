"""Builders for the non-runner Statistics views."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from datetime import tzinfo
from typing import cast

from sase.project_display_names import (
    ProjectDisplaySnapshot,
    humanize_cl_name,
    project_display_for,
)
from sase.stats._view_models import (
    ActivityView,
    PatchWorkRow,
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
    XPromptCountRow,
    XPromptFocusView,
    XPromptRow,
    XPromptsView,
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
    patch_rows: list[PatchWorkRow] = []
    for row in rows(work, "changespecs"):  # legacy wire key
        project = project_display_for(
            text(row.get("project"), "unknown"),
            snapshot=display_snapshot,
        )
        patch_key = text(row.get("name"), "unknown")
        patch_rows.append(
            PatchWorkRow(
                project_key=project.project_key,
                project_label=project.project_label,
                patch_key=patch_key,
                patch_label=humanize_cl_name(
                    patch_key,
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
    patches = tuple(patch_rows)
    patches_by_project: defaultdict[str, list[PatchWorkRow]] = defaultdict(list)
    for patch in patches:
        patches_by_project[patch.project_key].append(patch)

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
                distinct_patches=integer(
                    row.get("distinct_changespecs")  # legacy stats wire field
                ),
                unattributed_runs=integer(row.get("unattributed_runs")),
                total_runtime_seconds=number(row.get("total_runtime_seconds")),
                last_run_ts=number(row.get("last_run_ts")),
                patches=tuple(patches_by_project[project.project_key]),
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
    truncated = integer(
        work.get("truncated_changespec_rows"),  # legacy stats wire key
        integer(work.get("truncated_patch_rows")),
    )
    return ProjectsView(
        projects=projects,
        patches=patches,
        project_count=len(projects),
        patch_count=len(patches) + truncated,
        unattributed_runs=integer(work.get("unattributed_runs")),
        truncated_patch_rows=truncated,
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
        "patch",
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
        elif group_by == "patch":
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


def _xprompt_tags(payload: Payload) -> tuple[str, ...]:
    value = payload.get("tags")
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def _xprompt_count_rows(
    payload: Payload,
    key: str,
    owning_runs: int,
    display_snapshot: ProjectDisplaySnapshot,
    *,
    projects: bool = False,
) -> tuple[XPromptCountRow, ...]:
    count_rows_: list[XPromptCountRow] = []
    for row in rows(payload, key):
        row_key = text(row.get("name"), "unknown")
        label = (
            project_display_for(
                row_key,
                snapshot=display_snapshot,
            ).project_label
            if projects
            else row_key
        )
        count = integer(row.get("count"))
        count_rows_.append(
            XPromptCountRow(
                key=row_key,
                label=label,
                count=count,
                share=ratio(count, owning_runs),
            )
        )
    return tuple(count_rows_)


def build_xprompts_view(
    run_payload: Payload,
    display_snapshot: ProjectDisplaySnapshot,
    *,
    timezone: tzinfo,
) -> XPromptsView:
    """Build launch-boundary xprompt usage from the optional wire section."""
    section_value = run_payload.get("xprompts")
    if not isinstance(section_value, Mapping):
        return XPromptsView(
            available=False,
            runs_with_xprompts=0,
            runs_without_xprompts=0,
            distinct_xprompts=0,
            total_references=0,
            truncated_rows=0,
            rows=(),
            focus=None,
        )

    section = mapping(section_value)
    runs_with_xprompts = integer(section.get("runs_with_xprompts"))
    xprompt_rows: list[XPromptRow] = []
    for row in rows(section, "rows"):
        row_runs = integer(row.get("runs"))
        xprompt_rows.append(
            XPromptRow(
                name=text(row.get("name"), "unknown"),
                kind=text(row.get("kind"), "unknown"),
                tags=_xprompt_tags(row),
                runs=row_runs,
                references=integer(row.get("references")),
                distinct_agents=integer(row.get("distinct_agents")),
                completed=integer(row.get("completed")),
                failed=integer(row.get("failed")),
                success_rate=number(row.get("success_rate")),
                total_runtime_seconds=number(row.get("total_runtime_seconds")),
                mean_runtime_seconds=optional_number(row.get("mean_runtime_seconds")),
                first_run_ts=number(row.get("first_run_ts")),
                last_run_ts=number(row.get("last_run_ts")),
                share=ratio(row_runs, runs_with_xprompts),
                models=_xprompt_count_rows(
                    row,
                    "models",
                    row_runs,
                    display_snapshot,
                ),
                projects=_xprompt_count_rows(
                    row,
                    "projects",
                    row_runs,
                    display_snapshot,
                    projects=True,
                ),
                partners=_xprompt_count_rows(
                    row,
                    "partners",
                    row_runs,
                    display_snapshot,
                ),
            )
        )

    focus_value = section.get("focus")
    focus: XPromptFocusView | None = None
    if isinstance(focus_value, Mapping):
        focus_payload = mapping(focus_value)
        focus_runs = integer(focus_payload.get("runs"))
        bucket_seconds = integer(run_payload.get("bucket_seconds"), 86_400)
        focus = XPromptFocusView(
            name=text(focus_payload.get("name"), "unknown"),
            found=boolean(focus_payload.get("found")),
            kind=text(focus_payload.get("kind"), "unknown"),
            tags=_xprompt_tags(focus_payload),
            runs=focus_runs,
            references=integer(focus_payload.get("references")),
            distinct_agents=integer(focus_payload.get("distinct_agents")),
            completed=integer(focus_payload.get("completed")),
            failed=integer(focus_payload.get("failed")),
            success_rate=number(focus_payload.get("success_rate")),
            total_runtime_seconds=number(focus_payload.get("total_runtime_seconds")),
            mean_runtime_seconds=optional_number(
                focus_payload.get("mean_runtime_seconds")
            ),
            first_run_ts=number(focus_payload.get("first_run_ts")),
            last_run_ts=number(focus_payload.get("last_run_ts")),
            models=_xprompt_count_rows(
                focus_payload,
                "models",
                focus_runs,
                display_snapshot,
            ),
            projects=_xprompt_count_rows(
                focus_payload,
                "projects",
                focus_runs,
                display_snapshot,
                projects=True,
            ),
            partners=_xprompt_count_rows(
                focus_payload,
                "partners",
                focus_runs,
                display_snapshot,
            ),
            providers=_xprompt_count_rows(
                focus_payload,
                "providers",
                focus_runs,
                display_snapshot,
            ),
            tribes=_xprompt_count_rows(
                focus_payload,
                "tribes",
                focus_runs,
                display_snapshot,
            ),
            buckets=tuple(
                RunBucket(
                    start_ts=integer(row.get("start_ts")),
                    label=bucket_label(
                        integer(row.get("start_ts")),
                        bucket_seconds,
                        timezone,
                    ),
                    runs=integer(row.get("runs")),
                )
                for row in rows(focus_payload, "buckets")
            ),
        )

    return XPromptsView(
        available=True,
        runs_with_xprompts=runs_with_xprompts,
        runs_without_xprompts=integer(section.get("runs_without_xprompts")),
        distinct_xprompts=integer(section.get("distinct_xprompts")),
        total_references=integer(section.get("total_references")),
        truncated_rows=integer(section.get("truncated_rows")),
        rows=tuple(xprompt_rows),
        focus=focus,
    )


def build_plans_questions_view(
    _run_payload: Payload, activity_payload: Payload
) -> PlansQuestionsView:
    activity_plans = mapping(activity_payload.get("plans"))
    questions = mapping(activity_payload.get("questions"))
    return PlansQuestionsView(
        plans_proposed=integer(activity_plans.get("proposed")),
        plan_tiers=count_rows(rows(activity_plans, "tiers")),
        plans_approved=integer(activity_plans.get("approved")),
        plans_rejected=integer(activity_plans.get("rejected")),
        plans_feedback=integer(activity_plans.get("feedback")),
        plans_pending=integer(activity_plans.get("pending")),
        phases_per_epic=distribution_rows(rows(activity_plans, "phases_per_epic")),
        mean_phases_per_epic=number(activity_plans.get("mean_phases_per_epic")),
        question_sessions=integer(questions.get("sessions")),
        asking_agents=integer(questions.get("asking_agents")),
        questions=integer(questions.get("questions")),
        questions_per_session=distribution_rows(
            rows(questions, "questions_per_session")
        ),
        mean_questions_per_session=number(questions.get("mean_questions_per_session")),
        coverage_start_ts=optional_number(activity_payload.get("coverage_start_ts")),
    )
