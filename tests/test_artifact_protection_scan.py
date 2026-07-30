from __future__ import annotations

from pathlib import Path

import pytest

from sase._repo_inventory_models import RepoInventory, RepoRecord
from sase.core.artifact_file_protection import collect_protected_artifact_ids


def _record(
    name: str,
    path: Path,
    *,
    kind: str = "sidecar",
    exists: bool = True,
) -> RepoRecord:
    return RepoRecord(
        name=name,
        kind=kind,  # type: ignore[arg-type]
        project="sase",
        project_key="gh_sase-org__sase",
        path=str(path),
        exists=exists,
        auto_clone=False,
        description=None,
        source="test",
        env_name=None,
        slug=f"sase--{name}" if kind == "sidecar" else None,
    )


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
            _record("sase", tmp_path, kind="primary"),
            _record("plans", plans),
            _record("beads", beads),
            _record("research", research),
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

    result = collect_protected_artifact_ids()

    assert result.ids == frozenset(
        {
            "default:111111111111111111111111",
            "explicit:222222222222222222222222",
            "default:333333333333333333333333",
            "explicit:444444444444444444444444",
            "default:555555555555555555555555",
        }
    )
    assert result.sources_scanned == tuple(
        sorted(map(str, (projects, plans, beads, research)))
    )
    assert result.sources_unavailable == ()


def test_missing_required_sidecar_is_unavailable_but_research_is_optional(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    projects = tmp_path / "projects"
    plans = tmp_path / "plans"
    projects.mkdir()
    plans.mkdir()
    inventory = RepoInventory(
        (
            _record("sase", tmp_path, kind="primary"),
            _record("plans", plans),
            _record("beads", tmp_path / "missing-beads", exists=False),
            _record("research", tmp_path / "missing-research", exists=False),
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

    result = collect_protected_artifact_ids()

    assert result.sources_unavailable == ("sase:beads",)
    assert "sase:research" not in result.sources_unavailable
