"""Deterministic alias-history views for Launch Control PNG snapshots."""

from __future__ import annotations

from collections.abc import Iterable

from sase.core.agent_scan_wire_markers import UsedXPromptWire
from sase.llm_provider.alias_history import (
    AliasHistoryGroup,
    AliasHistoryProvenance,
    AliasHistoryRollupStatus,
    AliasHistoryRun,
    AliasHistoryStatusRollup,
    AliasHistoryView,
)

from sase.ace.tui.modals.alias_history_state import AliasHistoryEntryRequest

FROZEN_ALIAS_HISTORY_NOW = 1_786_881_600.0
VISUAL_INDEX_PATH = "/tmp/sase-visual-agent-artifacts.sqlite3"


def single_alias_entry() -> AliasHistoryEntryRequest:
    return AliasHistoryEntryRequest(
        aliases=("large",),
        title_label="@large",
        is_user_owned=False,
        effective_provider="claude",
        effective_model="opus",
        effective_effort="xhigh",
    )


def grouped_bucket_entry() -> AliasHistoryEntryRequest:
    return AliasHistoryEntryRequest(
        aliases=("research_a", "research_b", "research_c"),
        title_label="research bucket",
        is_user_owned=True,
    )


def custom_alias_entry() -> AliasHistoryEntryRequest:
    return AliasHistoryEntryRequest(
        aliases=("legacy_blog",),
        title_label="@legacy_blog",
        is_user_owned=True,
        effective_provider="codex",
        effective_model="o3",
    )


def empty_alias_entry() -> AliasHistoryEntryRequest:
    return AliasHistoryEntryRequest(
        aliases=("fresh_alias",),
        title_label="@fresh_alias",
        is_user_owned=True,
        effective_provider="claude",
        effective_model="haiku",
        effective_effort="low",
    )


def populated_alias_history_view() -> AliasHistoryView:
    return _view(
        aliases=("large",),
        limit_per_alias=10,
        groups=(
            _group(
                "large",
                total_count=4,
                runs=(
                    _direct_run(),
                    _indirect_run(),
                    _default_run(),
                    _unrecorded_run(),
                ),
            ),
        ),
    )


def grouped_alias_history_view() -> AliasHistoryView:
    return _view(
        aliases=("research_a", "research_b", "research_c"),
        limit_per_alias=10,
        groups=(
            _group(
                "research_a",
                total_count=2,
                runs=(
                    _direct_run(
                        alias="research_a",
                        agent_name="research_a.08m",
                        project_name="research",
                        started_at="2026-08-16T09:00:00+00:00",
                        artifact_dir="/visual/agents/research_a_08m",
                    ),
                    _unrecorded_run(
                        alias="research_a",
                        agent_name="research_a.07z",
                        project_name="research",
                        started_at="2026-08-15T18:00:00+00:00",
                        artifact_dir="/visual/agents/research_a_07z",
                    ),
                ),
            ),
            _group(
                "research_b",
                total_count=1,
                runs=(
                    _indirect_run(
                        alias="research_b",
                        via_alias="coder",
                        agent_name="research_b.10q",
                        project_name="sase",
                        started_at="2026-08-16T06:30:00+00:00",
                        artifact_dir="/visual/agents/research_b_10q",
                    ),
                ),
            ),
            _group("research_c", total_count=0, runs=()),
        ),
    )


def truncated_alias_history_view() -> AliasHistoryView:
    return _view(
        aliases=("large",),
        limit_per_alias=2,
        groups=(
            _group(
                "large",
                total_count=7,
                runs=(
                    _direct_run(
                        agent_name="sase-n8.land",
                        started_at="2026-08-16T11:18:00+00:00",
                        artifact_dir="/visual/agents/sase_n8_land",
                    ),
                    _default_run(
                        agent_name="adhoc.04p",
                        started_at="2026-08-16T08:45:00+00:00",
                        artifact_dir="/visual/agents/adhoc_04p",
                    ),
                ),
                truncated=True,
                limit=2,
            ),
        ),
    )


def legacy_only_alias_history_view() -> AliasHistoryView:
    return _view(
        aliases=("legacy_blog",),
        limit_per_alias=10,
        groups=(
            _group(
                "legacy_blog",
                total_count=2,
                runs=(
                    _unrecorded_run(
                        alias="legacy_blog",
                        agent_name="blog.002",
                        project_name="bob",
                        model="o3",
                        provider="codex",
                        effort=None,
                        started_at="2026-08-12T12:00:00+00:00",
                        artifact_dir="/visual/agents/blog_002",
                    ),
                    _unrecorded_run(
                        alias="legacy_blog",
                        agent_name="blog.001",
                        project_name="bob",
                        model="gpt-5.3-codex-spark",
                        provider="codex",
                        effort="high",
                        started_at="2026-08-10T15:00:00+00:00",
                        artifact_dir="/visual/agents/blog_001",
                    ),
                ),
            ),
        ),
    )


def empty_alias_history_view() -> AliasHistoryView:
    return _view(
        aliases=("fresh_alias",),
        limit_per_alias=10,
        groups=(_group("fresh_alias", total_count=0, runs=()),),
    )


def _direct_run(
    *,
    alias: str = "large",
    agent_name: str = "sase-n7.land",
    project_name: str = "sase",
    started_at: str = "2026-08-16T10:00:00+00:00",
    artifact_dir: str = "/visual/agents/sase_n7_land",
) -> AliasHistoryRun:
    return _run(
        alias=alias,
        artifact_dir=artifact_dir,
        agent_name=agent_name,
        project_name=project_name,
        started_at=started_at,
        status="done",
        has_done_marker=True,
        rollup_status="done",
        provenance=AliasHistoryProvenance(
            kind="direct",
            label="direct",
            origin="directive",
        ),
        model_alias_origin="directive",
        model_alias_trail=(alias,),
        alias_position=0,
        prompt_snippet=(
            "Refactor Launch Control's model-alias ownership module into focused "
            "siblings and keep the UI state stable while the modal is open."
        ),
        bead_id="sase-n7.6",
        cl_name="sase-n7",
        workspace_num=15,
        used_xprompts=(UsedXPromptWire(name="work_phase_bead", kind="workflow"),),
        duration_seconds=38 * 60 + 12,
    )


def _indirect_run(
    *,
    alias: str = "large",
    via_alias: str = "coder",
    agent_name: str = "03q--mon",
    project_name: str = "sase",
    started_at: str = "2026-08-16T07:00:00+00:00",
    artifact_dir: str = "/visual/agents/03q_mon",
) -> AliasHistoryRun:
    return _run(
        alias=alias,
        artifact_dir=artifact_dir,
        agent_name=agent_name,
        project_name=project_name,
        started_at=started_at,
        status="running",
        workflow_status="running",
        rollup_status="running",
        provenance=AliasHistoryProvenance(
            kind="indirect",
            label=f"via @{via_alias}",
            origin="directive",
            via_alias=via_alias,
        ),
        model_alias_origin="directive",
        model_alias_trail=(via_alias, alias),
        alias_position=1,
        prompt_snippet="Trace the indirect alias handoff through the core projection.",
        bead_id="sase-n8.2",
        workspace_num=3,
    )


def _default_run(
    *,
    alias: str = "large",
    agent_name: str = "bobo.w3",
    project_name: str = "bob",
    started_at: str = "2026-08-15T12:00:00+00:00",
    artifact_dir: str = "/visual/agents/bobo_w3",
) -> AliasHistoryRun:
    return _run(
        alias=alias,
        artifact_dir=artifact_dir,
        agent_name=agent_name,
        project_name=project_name,
        started_at=started_at,
        status="failed",
        workflow_status="failed",
        rollup_status="failed",
        provenance=AliasHistoryProvenance(
            kind="default",
            label="default",
            origin="default_model",
        ),
        model_alias_origin="default_model",
        model_alias_trail=(alias,),
        alias_position=0,
        prompt_snippet="Run the daily vault maintenance pass with the configured default.",
        bead_id="bob-18",
        cl_name="bob-maintenance",
        workspace_num=7,
        duration_seconds=91,
    )


def _unrecorded_run(
    *,
    alias: str = "large",
    agent_name: str = "tmp_260813",
    project_name: str = "sase",
    model: str = "sonnet",
    provider: str = "claude",
    effort: str | None = "high",
    started_at: str = "2026-08-13T11:30:00+00:00",
    artifact_dir: str = "/visual/agents/tmp_260813",
) -> AliasHistoryRun:
    return _run(
        alias=alias,
        artifact_dir=artifact_dir,
        agent_name=agent_name,
        project_name=project_name,
        model=model,
        provider=provider,
        effort=effort,
        started_at=started_at,
        status="done",
        has_done_marker=True,
        rollup_status="done",
        provenance=AliasHistoryProvenance(
            kind="unrecorded",
            label="unrecorded",
        ),
        model_alias_origin=None,
        model_alias_trail=(alias,),
        alias_position=0,
        prompt_snippet="Summarize a pre-migration launch whose alias origin is unknown.",
        workspace_num=12,
        duration_seconds=11 * 60,
    )


def _run(
    *,
    alias: str,
    artifact_dir: str,
    agent_name: str,
    project_name: str,
    started_at: str,
    status: str,
    rollup_status: AliasHistoryRollupStatus,
    provenance: AliasHistoryProvenance,
    model_alias_origin: str | None,
    model_alias_trail: tuple[str, ...],
    alias_position: int,
    model: str = "opus",
    provider: str = "claude",
    effort: str | None = "xhigh",
    workflow_status: str | None = None,
    has_done_marker: bool = False,
    hidden: bool = False,
    retry_attempt: int | None = None,
    bead_id: str | None = None,
    cl_name: str | None = None,
    workspace_num: int | None = None,
    prompt_snippet: str | None = None,
    used_xprompts: tuple[UsedXPromptWire, ...] = (),
    duration_seconds: float | None = None,
) -> AliasHistoryRun:
    return AliasHistoryRun(
        artifact_dir=artifact_dir,
        project_key=project_name,
        project_name=project_name,
        workflow_dir_name=f"{agent_name}.workflow",
        timestamp=started_at.replace("-", "").replace(":", "")[:14],
        alias_position=alias_position,
        status=status,
        has_done_marker=has_done_marker,
        hidden=hidden,
        provenance=provenance,
        rollup_status=rollup_status,
        agent_name=agent_name,
        workflow_name=agent_name,
        model=model,
        llm_provider=provider,
        reasoning_effort=effort,
        model_alias=alias,
        model_alias_origin=model_alias_origin,
        model_alias_trail=model_alias_trail,
        workflow_status=workflow_status,
        started_at=started_at,
        duration_seconds=duration_seconds,
        retry_attempt=retry_attempt,
        bead_id=bead_id,
        cl_name=cl_name,
        workspace_num=workspace_num,
        prompt_snippet=prompt_snippet,
        used_xprompts=used_xprompts,
    )


def _group(
    alias: str,
    *,
    total_count: int,
    runs: tuple[AliasHistoryRun, ...],
    truncated: bool = False,
    limit: int = 10,
) -> AliasHistoryGroup:
    return AliasHistoryGroup(
        alias=alias,
        limit=limit,
        total_count=total_count,
        returned_count=len(runs),
        truncated=truncated,
        status_rollup=_rollup(runs),
        runs=runs,
    )


def _view(
    *,
    aliases: tuple[str, ...],
    limit_per_alias: int,
    groups: tuple[AliasHistoryGroup, ...],
) -> AliasHistoryView:
    return AliasHistoryView(
        index_path=VISUAL_INDEX_PATH,
        aliases=aliases,
        limit_per_alias=limit_per_alias,
        include_hidden=False,
        projects=(),
        freshness="cached",
        groups=groups,
        status_rollup=_rollup(run for group in groups for run in group.runs),
    )


def _rollup(runs: Iterable[AliasHistoryRun]) -> AliasHistoryStatusRollup:
    done = failed = running = 0
    for run in runs:
        if run.rollup_status == "failed":
            failed += 1
        elif run.rollup_status == "running":
            running += 1
        else:
            done += 1
    return AliasHistoryStatusRollup(done=done, failed=failed, running=running)


__all__ = [
    "FROZEN_ALIAS_HISTORY_NOW",
    "custom_alias_entry",
    "empty_alias_entry",
    "empty_alias_history_view",
    "grouped_alias_history_view",
    "grouped_bucket_entry",
    "legacy_only_alias_history_view",
    "populated_alias_history_view",
    "single_alias_entry",
    "truncated_alias_history_view",
]
