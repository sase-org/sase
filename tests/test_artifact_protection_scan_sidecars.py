"""Sidecar-availability and managed/unmanaged project coverage.

Split from ``tests.test_artifact_protection_scan``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase._repo_inventory_models import RepoInventory
from sase.core.artifact_file_protection import collect_protected_artifact_ids
from sase.sdd.store import write_sdd_store_record
from tests._artifact_protection_scan_helpers import make_repo_record
from tests.main.repo_init_handler_helpers import _mark_managed_project

__all__ = [
    "test_connected_project_with_a_missing_clone_keeps_the_bare_label",
    "test_managed_unconnected_project_reports_both_required_roles",
    "test_missing_required_sidecar_is_unavailable_but_research_is_optional",
    "test_unmanaged_project_with_live_beads_clone_is_scanned",
    "test_unmanaged_unconnected_project_has_no_required_sources",
]


def test_missing_required_sidecar_is_unavailable_but_research_is_optional(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = tmp_path / "projects"
    plans = tmp_path / "plans"
    projects.mkdir()
    plans.mkdir()
    _mark_managed_project(tmp_path)
    inventory = RepoInventory(
        (
            make_repo_record("sase", tmp_path, kind="primary"),
            make_repo_record("plans", plans),
            make_repo_record("beads", tmp_path / "missing-beads", exists=False),
            make_repo_record("research", tmp_path / "missing-research", exists=False),
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

    # The fixture primary has no SDD store record: never connected here.
    assert result.sources_unavailable == (
        "sase:beads (sidecars not connected on this machine)",
    )
    assert not any(
        source.startswith("sase:research") for source in result.sources_unavailable
    )


def test_connected_project_with_a_missing_clone_keeps_the_bare_label(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = tmp_path / "projects"
    plans = tmp_path / "plans"
    projects.mkdir()
    plans.mkdir()
    write_sdd_store_record(
        tmp_path,
        {
            "storage": "separate_repo",
            "provider": "github",
            "remote_url": "https://example.test/sase--plans.git",
            "discovery": "found",
        },
    )
    inventory = RepoInventory(
        (
            make_repo_record("sase", tmp_path, kind="primary"),
            make_repo_record("plans", plans),
            make_repo_record("beads", tmp_path / "missing-beads", exists=False),
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

    assert result.sources_unavailable == ("sase:beads",)


def test_managed_unconnected_project_reports_both_required_roles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    _mark_managed_project(tmp_path)
    inventory = RepoInventory(
        (
            make_repo_record("sase", tmp_path, kind="primary"),
            make_repo_record("beads", tmp_path / "missing-beads", exists=False),
            make_repo_record("plans", tmp_path / "missing-plans", exists=False),
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

    assert result.sources_unavailable == (
        "sase:beads (sidecars not connected on this machine)",
        "sase:plans (sidecars not connected on this machine)",
    )


def test_unmanaged_unconnected_project_has_no_required_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = tmp_path / "projects"
    projects.mkdir()
    _mark_managed_project(tmp_path, config="is_sase_managed: false\n")
    inventory = RepoInventory(
        (
            make_repo_record("sase", tmp_path, kind="primary"),
            make_repo_record("beads", tmp_path / "missing-beads", exists=False),
            make_repo_record("plans", tmp_path / "missing-plans", exists=False),
            make_repo_record("research", tmp_path / "missing-research", exists=False),
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

    assert result.sources_unavailable == ()


def test_unmanaged_project_with_live_beads_clone_is_scanned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = tmp_path / "projects"
    beads = tmp_path / "beads"
    projects.mkdir()
    beads.mkdir()
    stored_id = "default:111111111111111111111111"
    (beads / "page.md").write_text(
        f"file:{stored_id}\n",
        encoding="utf-8",
    )
    _mark_managed_project(tmp_path, config="is_sase_managed: false\n")
    inventory = RepoInventory(
        (
            make_repo_record("sase", tmp_path, kind="primary"),
            make_repo_record("beads", beads),
            make_repo_record("plans", tmp_path / "missing-plans", exists=False),
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

    assert stored_id in result.referenced_ids
    assert result.sources_unavailable == ()
