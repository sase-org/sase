"""Project/plan/bead/research collection and bead-projection coverage.

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
    "test_bead_ref_stays_protected_after_projection_is_gone",
    "test_bead_store_projection_is_not_scanned_under_other_sidecar_roles",
    "test_bead_store_projection_protects_refs_without_a_published_page",
    "test_collects_and_normalizes_project_plan_bead_and_research_refs",
]


def test_collects_and_normalizes_project_plan_bead_and_research_refs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = tmp_path / "projects"
    plans = tmp_path / "plans"
    beads = tmp_path / "beads"
    research = tmp_path / "research"
    projects.mkdir()
    plans.mkdir()
    beads.mkdir()
    research.mkdir()
    (projects / "sase.sase").write_text(
        "CL/PR: file:default:111111111111111111111111\n",
        encoding="utf-8",
    )
    (projects / "sase-archive.sase").write_text(
        "COMMENTS: explicit:222222222222222222222222\n",
        encoding="utf-8",
    )
    (plans / "design.md").write_text(
        "default:333333333333333333333333\n",
        encoding="utf-8",
    )
    (beads / "page.md").write_text(
        "file:explicit:444444444444444444444444\n",
        encoding="utf-8",
    )
    (research / "report.txt").write_text(
        "default:555555555555555555555555\n",
        encoding="utf-8",
    )
    git_dir = plans / ".git"
    git_dir.mkdir()
    (git_dir / "ignored.md").write_text(
        "default:aaaaaaaaaaaaaaaaaaaaaaaa\n",
        encoding="utf-8",
    )
    (plans / "ignored.py").write_text(
        "default:bbbbbbbbbbbbbbbbbbbbbbbb\n",
        encoding="utf-8",
    )

    inventory = RepoInventory(
        (
            make_repo_record("sase", tmp_path, kind="primary"),
            make_repo_record("plans", plans),
            make_repo_record("beads", beads),
            make_repo_record("research", research),
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

    expected = frozenset(
        {
            "default:111111111111111111111111",
            "explicit:222222222222222222222222",
            "default:333333333333333333333333",
            "explicit:444444444444444444444444",
            "default:555555555555555555555555",
        }
    )
    assert result.referenced_ids == expected
    assert result.consumed_ids == frozenset()
    assert result.overlap_ids == frozenset()
    assert result.ids == expected
    assert result.sources_scanned == tuple(
        sorted(map(str, (projects, plans, beads, research)))
    )
    assert result.sources_unavailable == ()


def test_bead_store_projection_protects_refs_without_a_published_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = tmp_path / "projects"
    plans = tmp_path / "plans"
    beads = tmp_path / "beads"
    for path in (projects, plans, beads):
        path.mkdir()
    stored_id = "default:111111111111111111111111"
    detached_id = "explicit:222222222222222222222222"
    (beads / "issues.jsonl").write_text(
        f'{{"id":"sase-1","refs":["file:{stored_id}"]}}\n',
        encoding="utf-8",
    )
    streams = beads / "events" / "streams"
    streams.mkdir(parents=True)
    (streams / "sase-1.jsonl").write_text(
        f'{{"operation":"ReferenceRemoved","reference":"file:{detached_id}"}}\n',
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

    assert result.referenced_ids == frozenset({stored_id})
    assert detached_id not in result.ids
    assert result.sources_unavailable == ()


def test_bead_ref_stays_protected_after_projection_is_gone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bead-referenced artifact stays protected with no issues.jsonl.

    Regression test for projection-off (sase-1h8.11): references come from
    the ``bead_referenced_artifact_ids`` core query over current state, so
    removing the on-demand export must not shrink protection coverage. The
    core query itself is covered in sase-core; here the installed core is
    simulated by patching the facade.
    """
    projects = tmp_path / "projects"
    plans = tmp_path / "plans"
    beads = tmp_path / "beads"
    for path in (projects, plans, beads):
        path.mkdir()
    stored_id = "default:111111111111111111111111"
    assert not (beads / "issues.jsonl").exists()
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
    monkeypatch.setattr(
        "sase.core.bead_read_facade.referenced_artifact_ids",
        lambda _beads_dir: frozenset({stored_id}),
    )

    result = collect_protected_artifact_ids()

    assert stored_id in result.referenced_ids
    assert stored_id in result.ids
    assert result.sources_unavailable == ()


def test_bead_store_projection_is_not_scanned_under_other_sidecar_roles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = tmp_path / "projects"
    plans = tmp_path / "plans"
    beads = tmp_path / "beads"
    for path in (projects, plans, beads):
        path.mkdir()
    (plans / "issues.jsonl").write_text(
        '{"refs":["file:default:333333333333333333333333"]}\n',
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

    assert result.referenced_ids == frozenset()
