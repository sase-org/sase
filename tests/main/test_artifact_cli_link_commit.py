"""CLI integration: explicit artifact-link commands commit per sidecar."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess

import pytest

from sase.artifact_cli.link_ops import handle_link_add, handle_link_rm
from sase.sdd._artifact_link_ignore import ARTIFACT_LINK_LOCK_GITIGNORE_PATTERN
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _init_git(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "SASE Test"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "sase-test@example.invalid"],
        cwd=repo,
        check=True,
    )
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-q", "-m", "initial")


def _commit_count(repo: Path) -> int:
    return int(_run_git(repo, "rev-list", "--count", "HEAD").strip())


def _head_files(repo: Path) -> set[str]:
    names = _run_git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD")
    return {line for line in names.splitlines() if line.strip()}


def _head_subject(repo: Path) -> str:
    return _run_git(repo, "log", "-1", "--pretty=%s").strip()


def _patch_store(monkeypatch: pytest.MonkeyPatch, store: ArtifactLinkStore) -> None:
    monkeypatch.setattr(
        "sase.artifact_cli.link_ops.resolve_artifact_link_store",
        lambda: store,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.link_ops._created_by",
        lambda: "bbugyi200.athena.y2",
    )
    monkeypatch.setattr(
        "sase.artifact_cli.link_ops._created_at",
        lambda: "2026-08-21T00:00:00Z",
    )
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"sdd": {"push_after_commit": False}},
    )


def _add_args(source: str, relation: str, target: str, why: str) -> argparse.Namespace:
    return argparse.Namespace(
        source_ref=source,
        relation=relation,
        target_ref=target,
        why=why,
    )


def test_add_commits_one_sidecar_for_two_indexes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans = tmp_path / "plans"
    _init_git(plans)
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans},
    )
    _patch_store(monkeypatch, store)
    before = _commit_count(plans)

    assert (
        handle_link_add(
            _add_args(
                "plan:202608/a.md",
                "related",
                "plan:202608/b.md",
                "shares a root cause",
            )
        )
        == 0
    )

    assert _commit_count(plans) == before + 1
    assert _head_subject(plans) == "chore(artifact-links): persist link indexes"
    files = _head_files(plans)
    assert "links/202608/a.md.json" in files
    assert "links/202608/b.md.json" in files
    assert ".gitignore" in files
    assert ARTIFACT_LINK_LOCK_GITIGNORE_PATTERN in (plans / ".gitignore").read_text(
        encoding="utf-8"
    )
    assert "links/202608/a.md.lock" not in files
    assert "links/202608/b.md.lock" not in files
    status = _run_git(plans, "status", "--porcelain", "--untracked-files=all")
    assert status == ""
    assert (plans / "links" / "202608" / "a.md.lock").is_file()


def test_noop_add_creates_zero_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans = tmp_path / "plans"
    _init_git(plans)
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans},
    )
    _patch_store(monkeypatch, store)
    args = _add_args(
        "plan:202608/a.md",
        "related",
        "plan:202608/b.md",
        "shares a root cause",
    )
    assert handle_link_add(args) == 0
    after_add = _commit_count(plans)
    assert handle_link_add(args) == 0
    assert _commit_count(plans) == after_add
    assert _run_git(plans, "status", "--porcelain") == ""


def test_relation_removal_commits_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans = tmp_path / "plans"
    _init_git(plans)
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans},
    )
    _patch_store(monkeypatch, store)
    assert (
        handle_link_add(
            _add_args(
                "plan:202608/a.md",
                "implements",
                "plan:202608/b.md",
                "lands the design",
            )
        )
        == 0
    )
    after_add = _commit_count(plans)

    assert (
        handle_link_rm(
            argparse.Namespace(
                source_ref="plan:202608/a.md",
                target_ref="plan:202608/b.md",
                relation="implements",
            )
        )
        == 0
    )
    assert _commit_count(plans) == after_add + 1
    files = _head_files(plans)
    assert "links/202608/a.md.json" in files
    assert "links/202608/b.md.json" in files
    assert not any(name.endswith(".lock") for name in files)


def test_document_endpoints_across_two_sidecars_commit_each_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans = tmp_path / "plans"
    research = tmp_path / "research"
    _init_git(plans)
    _init_git(research)
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans, "research": research},
    )
    _patch_store(monkeypatch, store)
    plans_before = _commit_count(plans)
    research_before = _commit_count(research)

    assert (
        handle_link_add(
            _add_args(
                "plan:202608/a.md",
                "derives-from",
                "research:202608/source.md",
                "uses its measurements",
            )
        )
        == 0
    )

    assert _commit_count(plans) == plans_before + 1
    assert _commit_count(research) == research_before + 1
    assert "links/202608/a.md.json" in _head_files(plans)
    assert "links/202608/source.md.json" in _head_files(research)
    assert _run_git(plans, "status", "--porcelain") == ""
    assert _run_git(research, "status", "--porcelain") == ""


def test_bead_to_document_commits_document_and_bead_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.model import IssueType
    from sase.bead.project import BEADS_DIRNAME_ROOT, BeadProject

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans = tmp_path / "plans"
    beads_repo = tmp_path / "beads"
    _init_git(plans)
    _init_git(beads_repo)
    with BeadProject.init(beads_repo, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        issue = project.create("Linked bead", IssueType.PLAN)
        store = ArtifactLinkStore(
            project_key="gh_sase-org__sase",
            sidecar_roots={"plan": plans},
            beads_dir=project.beads_dir,
        )
        _patch_store(monkeypatch, store)
        plans_before = _commit_count(plans)
        beads_before = _commit_count(beads_repo)

        assert (
            handle_link_add(
                _add_args(
                    f"bead:{issue.id}",
                    "related",
                    "plan:202608/a.md",
                    "tracks the same failure",
                )
            )
            == 0
        )

        assert _commit_count(plans) == plans_before + 1
        assert _commit_count(beads_repo) == beads_before + 1
        assert _head_subject(beads_repo) == "chore(beads): update artifact links"
        assert "links/202608/a.md.json" in _head_files(plans)
        assert not list((plans / "links").rglob("*bead*"))


def test_bead_to_bead_commits_only_the_bead_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.bead.model import IssueType
    from sase.bead.project import BEADS_DIRNAME_ROOT, BeadProject

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    plans = tmp_path / "plans"
    beads_repo = tmp_path / "beads"
    _init_git(plans)
    _init_git(beads_repo)
    with BeadProject.init(beads_repo, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        left = project.create("Left", IssueType.PLAN)
        right = project.create("Right", IssueType.PLAN)
        store = ArtifactLinkStore(
            project_key="gh_sase-org__sase",
            sidecar_roots={"plan": plans},
            beads_dir=project.beads_dir,
        )
        _patch_store(monkeypatch, store)
        plans_before = _commit_count(plans)
        beads_before = _commit_count(beads_repo)

        assert (
            handle_link_add(
                _add_args(
                    f"bead:{left.id}",
                    "related",
                    f"bead:{right.id}",
                    "shares a root cause",
                )
            )
            == 0
        )

        assert _commit_count(plans) == plans_before
        assert _commit_count(beads_repo) == beads_before + 1
        assert list(plans.rglob("*.json")) == []
        assert _run_git(plans, "status", "--porcelain") == ""
