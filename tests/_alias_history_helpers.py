"""Shared builders for alias-history rendering/state/modal tests."""

from __future__ import annotations

from sase.ace.tui.modals.alias_history_state import AliasHistoryEntryRequest
from sase.llm_provider.alias_history import (
    AliasHistoryGroup,
    _AliasHistoryProvenance,
    AliasHistoryRun,
    _AliasHistoryStatusRollup,
    AliasHistoryView,
)


def make_run(**overrides: object) -> AliasHistoryRun:
    payload: dict[str, object] = {
        "artifact_dir": "/tmp/a",
        "project_key": "gh_sase-org__sase",
        "project_name": "sase",
        "workflow_dir_name": "ace-run",
        "timestamp": "20260816120000",
        "alias_position": 0,
        "status": "done",
        "has_done_marker": True,
        "hidden": False,
        "provenance": _AliasHistoryProvenance(kind="direct", label="direct"),
        "rollup_status": "done",
        "agent_name": "worker_1",
        "model": "opus",
        "llm_provider": "claude",
        "reasoning_effort": "high",
    }
    payload.update(overrides)
    return AliasHistoryRun(**payload)  # type: ignore[arg-type]


def make_group(
    alias: str, runs: list[AliasHistoryRun], *, limit: int = 10, truncated: bool = False
) -> AliasHistoryGroup:
    done = sum(1 for run in runs if run.rollup_status == "done")
    failed = sum(1 for run in runs if run.rollup_status == "failed")
    running = sum(1 for run in runs if run.rollup_status == "running")
    return AliasHistoryGroup(
        alias=alias,
        limit=limit,
        total_count=len(runs),
        returned_count=len(runs),
        truncated=truncated,
        status_rollup=_AliasHistoryStatusRollup(
            done=done, failed=failed, running=running
        ),
        runs=tuple(runs),
    )


def make_view(groups: list[AliasHistoryGroup], **overrides: object) -> AliasHistoryView:
    payload: dict[str, object] = {
        "index_path": "/tmp/index.sqlite",
        "aliases": tuple(group.alias for group in groups),
        "limit_per_alias": 10,
        "include_hidden": False,
        "projects": (),
        "freshness": "cached",
        "groups": tuple(groups),
        "status_rollup": _AliasHistoryStatusRollup(
            done=sum(g.status_rollup.done for g in groups),
            failed=sum(g.status_rollup.failed for g in groups),
            running=sum(g.status_rollup.running for g in groups),
        ),
    }
    payload.update(overrides)
    return AliasHistoryView(**payload)  # type: ignore[arg-type]


def make_entry(
    aliases: tuple[str, ...] = ("large",), **overrides: object
) -> AliasHistoryEntryRequest:
    payload: dict[str, object] = {
        "aliases": aliases,
        "title_label": f"@{aliases[0]}" if len(aliases) == 1 else "bucket",
        "is_user_owned": False,
    }
    payload.update(overrides)
    return AliasHistoryEntryRequest(**payload)  # type: ignore[arg-type]
