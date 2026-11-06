"""Shared fixtures for axe chop output-contract tests.

Not a conftest so the fixtures only apply when a test file opts in by
importing the re-exported name as an autouse fixture.

Split from ``tests.test_axe_chop_output_contract_retention``; the retention
builders below are public so the retention split modules can share them
without importing ``_``-prefixed names across files.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.axe.chop_script_context import ChopScriptContext, write_chop_context
from sase.core.agent_artifact_run_retention_models import (
    AceRunProtectionSnapshot,
    AceRunRetentionCounts,
    AceRunRetentionItem,
    AceRunRetentionPlan,
    AceRunRetentionPolicy,
    EmptyAceRunShard,
)
from sase.core.time import get_timezone

__all__ = [
    "assert_configured_aware_timestamp",
    "isolate_chop_result_file",
    "retention_empty_shard",
    "retention_plan",
    "retention_purge_result",
    "retention_selected_item",
    "write_output_contract_context",
]


@pytest.fixture(autouse=True)
def isolate_chop_result_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep an outer chop runner from overriding each test context.

    Importing this fixture's name into a test module is enough for pytest to
    pick it up, since fixture discovery scans the module's own namespace.
    """

    monkeypatch.delenv("SASE_CHOP_RESULT_FILE", raising=False)


@pytest.fixture(autouse=True)
def _isolate_chop_result_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Legacy alias kept for modules still importing the private name."""

    monkeypatch.delenv("SASE_CHOP_RESULT_FILE", raising=False)


def write_output_contract_context(tmp_path: Path, result_path: Path) -> Path:
    context_path = tmp_path / "context.json"
    write_chop_context(
        ChopScriptContext(
            max_hook_runners=1,
            max_agent_runners=1,
            zombie_timeout_seconds=60,
            query="",
            lumberjack_name="test",
            state_dir=str(tmp_path),
            all_patches_file=str(tmp_path / "all.json"),
            filtered_patches_file=str(tmp_path / "filtered.json"),
            result_file=str(result_path),
        ),
        str(context_path),
    )
    return context_path


def _write_context(tmp_path: Path, result_path: Path) -> Path:
    """Legacy alias kept for modules still importing the private name."""

    return write_output_contract_context(tmp_path, result_path)


def assert_configured_aware_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None
    expected_offset = get_timezone().utcoffset(parsed.replace(tzinfo=None))
    assert parsed.utcoffset() == expected_offset
    return parsed


def retention_plan(
    *,
    selected: tuple[AceRunRetentionItem, ...] = (),
    empty_shards: tuple[EmptyAceRunShard, ...] = (),
    sources_unavailable: tuple[str, ...] = (),
    reclaimable_bytes: int = 0,
) -> AceRunRetentionPlan:
    counts = AceRunRetentionCounts(
        candidates=len(selected),
        selected=len(selected),
        empty_out_of_range_shards=len(empty_shards),
        protected=0,
        truncated=0,
    )
    return AceRunRetentionPlan(
        policy=AceRunRetentionPolicy(
            now=datetime(2026, 1, 15, 12, 0, 0),
            keep_recent_months=2,
        ),
        protections=AceRunProtectionSnapshot(),
        selected=selected,
        protected=(),
        empty_out_of_range_shards=empty_shards,
        counts=counts,
        reclaimable_bytes=reclaimable_bytes,
        sources_unavailable=sources_unavailable,
    )


def retention_selected_item(tmp_path: Path) -> AceRunRetentionItem:
    return AceRunRetentionItem(
        project="proj",
        timestamp="20260101000000",
        artifact_dir=str(tmp_path / "proj" / "artifacts" / "ace-run" / "old-run"),
        size_bytes=2048,
        reason="older_than_recent_2_months",
    )


def retention_empty_shard(tmp_path: Path) -> EmptyAceRunShard:
    return EmptyAceRunShard(
        project="proj",
        kind="day",
        path=str(tmp_path / "proj" / "artifacts" / "ace-run" / "202501" / "01"),
        reason="outside_startup_shard_window",
    )


def retention_purge_result(**overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "purged": 0,
        "restored": 0,
        "freed_bytes": 0,
        "blocked_reason": None,
        "errors": 0,
        "index_errors": (),
    }
    values.update(overrides)
    return SimpleNamespace(**values)
