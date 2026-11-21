"""Consumption-ledger and artifact-link aggregate coverage.

Split from ``tests.test_artifact_protection_scan``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase._repo_inventory_models import RepoInventory
from sase.core.artifact_file_protection import collect_protected_artifact_ids
from tests._artifact_protection_scan_helpers import make_repo_record

__all__ = [
    "test_artifact_link_aggregate_protects_linked_file_ids",
    "test_consumption_adds_only_canonical_file_ids_and_retains_overlap_evidence",
    "test_missing_consumption_ledger_is_an_empty_optional_source",
    "test_query_failure_marks_present_consumption_ledger_unavailable",
]


def test_consumption_adds_only_canonical_file_ids_and_retains_overlap_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = tmp_path / "projects"
    plans = tmp_path / "plans"
    beads = tmp_path / "beads"
    ledger = tmp_path / "consumption.jsonl"
    for path in (projects, plans, beads):
        path.mkdir()
    ledger.touch()
    overlap_id = "default:111111111111111111111111"
    consumed_only_id = "explicit:222222222222222222222222"
    (projects / "sase.sase").write_text(
        f"COMMENTS: file:{overlap_id}\n",
        encoding="utf-8",
    )
    inventory = RepoInventory(
        (
            make_repo_record("sase", tmp_path, kind="primary"),
            make_repo_record("plans", plans),
            make_repo_record("beads", beads),
        )
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.sase_projects_dir",
        lambda: projects,
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.collect_repo_inventory",
        lambda: inventory,
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.default_artifact_consumption_log_path",
        lambda: ledger,
    )
    query_calls: list[Path | str | None] = []

    def summarize(*, log_path: Path | str | None = None):  # type: ignore[no-untyped-def]
        query_calls.append(log_path)
        return {
            f"file:{overlap_id}": object(),
            f"file:{consumed_only_id}": object(),
            "plan:202607/report.md": object(),
            f"file:{consumed_only_id}#L2": object(),
            "file:default:AAAAAAAAAAAAAAAAAAAAAAAA": object(),
        }

    monkeypatch.setattr(
        "sase.core.artifact_file_protection.summarize_artifact_consumption",
        summarize,
    )

    result = collect_protected_artifact_ids()

    assert query_calls == [ledger]
    assert result.referenced_ids == frozenset({overlap_id})
    assert result.consumed_ids == frozenset({overlap_id, consumed_only_id})
    assert result.overlap_ids == frozenset({overlap_id})
    assert result.ids == frozenset({overlap_id, consumed_only_id})
    assert str(ledger) in result.sources_scanned
    assert result.sources_unavailable == ()


def test_missing_consumption_ledger_is_an_empty_optional_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = tmp_path / "projects"
    plans = tmp_path / "plans"
    beads = tmp_path / "beads"
    for path in (projects, plans, beads):
        path.mkdir()
    ledger = tmp_path / "missing-consumption.jsonl"
    inventory = RepoInventory(
        (
            make_repo_record("sase", tmp_path, kind="primary"),
            make_repo_record("plans", plans),
            make_repo_record("beads", beads),
        )
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.sase_projects_dir",
        lambda: projects,
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.collect_repo_inventory",
        lambda: inventory,
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.default_artifact_consumption_log_path",
        lambda: ledger,
    )

    def unexpected_query(**_kwargs: object) -> object:
        raise AssertionError("missing ledgers must not be queried")

    monkeypatch.setattr(
        "sase.core.artifact_file_protection.summarize_artifact_consumption",
        unexpected_query,
    )

    result = collect_protected_artifact_ids()

    assert result.consumed_ids == frozenset()
    assert str(ledger) not in result.sources_scanned
    assert result.sources_unavailable == ()


def test_query_failure_marks_present_consumption_ledger_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = tmp_path / "projects"
    plans = tmp_path / "plans"
    beads = tmp_path / "beads"
    ledger = tmp_path / "consumption.jsonl"
    for path in (projects, plans, beads):
        path.mkdir()
    ledger.touch()
    inventory = RepoInventory(
        (
            make_repo_record("sase", tmp_path, kind="primary"),
            make_repo_record("plans", plans),
            make_repo_record("beads", beads),
        )
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.sase_projects_dir",
        lambda: projects,
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.collect_repo_inventory",
        lambda: inventory,
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.default_artifact_consumption_log_path",
        lambda: ledger,
    )

    def failing_query(**_kwargs: object) -> object:
        raise RuntimeError("query failed")

    monkeypatch.setattr(
        "sase.core.artifact_file_protection.summarize_artifact_consumption",
        failing_query,
    )

    result = collect_protected_artifact_ids()

    assert result.consumed_ids == frozenset()
    assert str(ledger) not in result.sources_scanned
    assert result.sources_unavailable == (f"{ledger}: query failed",)


def test_artifact_link_aggregate_protects_linked_file_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = tmp_path / "projects"
    plans = tmp_path / "plans"
    beads = tmp_path / "beads"
    for path in (projects, plans, beads):
        path.mkdir()
    linked_id = "explicit:aaaaaaaaaaaaaaaaaaaaaaaa"
    aggregate = projects / "gh_sase-org__sase" / "artifact-links.json"
    aggregate.parent.mkdir()
    aggregate.write_text(
        '{"schema_version": 2, "rows": [{'
        f'"source_ref": "file:{linked_id}", '
        '"target_ref": "plan:202608/a.md"}]}',
        encoding="utf-8",
    )
    inventory = RepoInventory(
        (
            make_repo_record("sase", tmp_path, kind="primary"),
            make_repo_record("plans", plans),
            make_repo_record("beads", beads),
        )
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.sase_projects_dir",
        lambda: projects,
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.collect_repo_inventory",
        lambda: inventory,
    )
    monkeypatch.setattr(
        "sase.core.artifact_file_protection.default_artifact_consumption_log_path",
        lambda: tmp_path / "missing-consumption.jsonl",
    )

    result = collect_protected_artifact_ids()

    assert linked_id in result.referenced_ids
    assert linked_id in result.ids
    assert str(aggregate) in result.sources_scanned
