"""Publication verification for committed bead-store mutations.

Regression coverage for the failure where a `sase bead close` run inside an
ephemeral workspace committed to a workspace-local sidecar clone, printed
``✓ Closed``, and lost the mutation when the clone was evicted.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest

from sase.bead import cli as bead_cli
from sase.bead.cli_common import BeadPublicationError
from sase.bead.cli_location import BeadsLocation
from sase.bead.model import IssueType, Status
from sase.bead.project import BEADS_DIRNAME_ROOT, BeadProject
from sase.bead.sync import verify_bead_store_published
from sase.sdd.store import SddStore

from .sync_test_helpers import configure_git_identity


def _bead_store_clone(tmp_path: Path) -> tuple[Path, Path]:
    """Build a bead-store clone with an upstream, as a workspace sidecar has."""
    bare = tmp_path / "beads.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)],
        capture_output=True,
        check=True,
    )
    clone = tmp_path / "workspace" / "sase" / "repos" / "beads"
    clone.parent.mkdir(parents=True)
    subprocess.run(
        ["git", "clone", str(bare), str(clone)],
        capture_output=True,
        check=True,
    )
    configure_git_identity(clone)
    with BeadProject.init(clone, beads_dirname=BEADS_DIRNAME_ROOT):
        pass
    subprocess.run(["git", "add", "-A"], cwd=clone, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init bead store"],
        cwd=clone,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "push", "-u", "origin", "HEAD:main"],
        cwd=clone,
        capture_output=True,
        check=True,
    )
    return clone, bare


def _remote_bead_subjects(bare: Path) -> list[str]:
    result = subprocess.run(
        ["git", "log", "--format=%s", "main"],
        cwd=bare,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


@pytest.fixture
def workspace_bead_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    """Route bead-store resolution at a sidecar-style clone with an upstream."""
    clone, bare = _bead_store_clone(tmp_path)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    location = BeadsLocation(
        root=clone,
        beads_dirname=BEADS_DIRNAME_ROOT,
        storage="sidecar_repos",
        store=SddStore(
            storage="sidecar_repos",
            sdd_dir=clone,
            repo_root=clone,
            sidecar_role="beads",
        ),
    )
    monkeypatch.setattr(
        "sase.bead.cli_common.resolve_beads_location",
        lambda *_args, **_kwargs: location,
    )
    monkeypatch.setattr(
        "sase.bead.cli_location.resolve_beads_location",
        lambda *_args, **_kwargs: location,
    )
    # The store integration marker is fresh right after a sync, which is
    # exactly when the TTL-gated background refresh declines to publish.
    from sase.bead.sync import mark_bead_integration

    mark_bead_integration(clone)
    monkeypatch.setattr("sase.bead.sync.schedule_current_bead_refresh", lambda: None)
    # Model the configured push policy missing this checkout: the sidecar
    # branch enqueues a request that drains against the primary checkout.
    monkeypatch.setattr(
        "sase.bead.cli_common._push_committed_bead_store",
        lambda **_kwargs: None,
    )
    monkeypatch.chdir(clone)
    return clone, bare


def test_close_publishes_when_the_configured_push_policy_missed_the_checkout(
    workspace_bead_store: tuple[Path, Path],
) -> None:
    clone, bare = workspace_bead_store
    with BeadProject(clone, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        issue = project.create("Workspace close", IssueType.PLAN)

    bead_cli.handle_bead_close(
        argparse.Namespace(ids=[issue.id], reason="done", note="verified")
    )

    assert f"chore(beads): close {issue.id}" in _remote_bead_subjects(bare)
    assert verify_bead_store_published(clone).published is True


def test_unpublishable_close_fails_loudly_instead_of_printing_closed(
    workspace_bead_store: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    clone, bare = workspace_bead_store
    with BeadProject(clone, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        issue = project.create("Doomed close", IssueType.PLAN)
    subprocess.run(
        ["git", "remote", "set-url", "origin", str(bare.parent / "missing.git")],
        cwd=clone,
        capture_output=True,
        check=True,
    )

    with pytest.raises(BeadPublicationError):
        bead_cli.handle_bead_close(
            argparse.Namespace(ids=[issue.id], reason="done", note="verified")
        )

    captured = capsys.readouterr()
    assert "✓ Closed" not in captured.out
    assert "was committed locally but NOT published" in captured.err
    assert "unpublished bead commit(s): 1" in captured.err
    assert str(clone) in captured.err
    assert f"git -C {clone} push" in captured.err
    # The close is still recorded locally, so the operator can republish it.
    with BeadProject(clone, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        assert project.show(issue.id).status is Status.CLOSED


def test_fast_path_mutation_reports_unpublished_state(
    workspace_bead_store: tuple[Path, Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.main import bead_fast_path

    clone, bare = workspace_bead_store
    with BeadProject(clone, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        issue = project.create(
            "Fast path update", IssueType.TASK, task_type="bug", size="small"
        )
        project.update(issue.id, status="in_progress")
    subprocess.run(
        ["git", "remote", "set-url", "origin", str(bare.parent / "missing.git")],
        cwd=clone,
        capture_output=True,
        check=True,
    )

    published = bead_fast_path._apply_mutation_side_effects(
        clone,
        {"operation": "update", "changed": True, "issue_ids": [issue.id]},
    )

    assert published is False
    assert "was committed locally but NOT published" in capsys.readouterr().err


def test_fast_path_mutation_publishes_through_the_same_verification(
    workspace_bead_store: tuple[Path, Path],
) -> None:
    from sase.main import bead_fast_path

    clone, bare = workspace_bead_store
    with BeadProject(clone, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        issue = project.create(
            "Fast path update", IssueType.TASK, task_type="bug", size="small"
        )
        project.update(issue.id, status="in_progress")

    published = bead_fast_path._apply_mutation_side_effects(
        clone,
        {"operation": "update", "changed": True, "issue_ids": [issue.id]},
    )

    assert published is True
    assert f"chore(beads): update {issue.id}" in _remote_bead_subjects(bare)


def test_verification_is_not_applicable_without_an_upstream(tmp_path: Path) -> None:
    repo = tmp_path / "local-store"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
    configure_git_identity(repo)
    (repo / "issues.jsonl").write_text("{}\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "local only"],
        cwd=repo,
        capture_output=True,
        check=True,
    )

    status = verify_bead_store_published(repo)

    assert status.applicable is False
    assert status.has_upstream is False
    assert status.published is True


def test_verification_is_not_applicable_for_an_in_tree_store(tmp_path: Path) -> None:
    beads_dir = tmp_path / "sdd" / "beads"
    beads_dir.mkdir(parents=True)

    status = verify_bead_store_published(beads_dir)

    assert status.applicable is False
    assert status.published is True


def test_close_on_a_store_without_a_remote_stays_silent(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as project:
        issue = project.create("No remote", IssueType.PLAN)

    bead_cli.handle_bead_close(argparse.Namespace(ids=[issue.id], reason="done"))

    captured = capsys.readouterr()
    assert "✓ Closed" in captured.out
    assert "NOT published" not in captured.err
