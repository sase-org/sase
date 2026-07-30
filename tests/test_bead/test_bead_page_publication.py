"""Post-commit publication coverage for generated bead pages."""

from __future__ import annotations

import json
import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import MappingProxyType

import pytest

from sase.bead.model import Issue, IssueType
from sase.bead.project import BEADS_DIRNAME_ROOT, BeadProject
from sase.bead_pages.associations import BeadAssociationIndex
from sase.bead_pages.publication import publish_committed_bead_pages
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from sase.core.paths import sase_projects_dir
from sase.sdd.store import SddStore
from sase.workflows.commit.checkpoint import CommitCheckpoint
from sase.workflows.commit.workflow import CommitWorkflow, RunResult


class _View:
    def __init__(self, issues: tuple[Issue, ...]) -> None:
        self._issues = {issue.id: issue for issue in issues}

    def __enter__(self) -> _View:
        return self

    def __exit__(self, *_args: object) -> None:
        pass

    def show(self, issue_id: str) -> Issue:
        return self._issues[issue_id]

    def list_issues(self) -> list[Issue]:
        return list(self._issues.values())

    def get_epic_children(self, issue_id: str) -> list[Issue]:
        return [issue for issue in self._issues.values() if issue.parent_id == issue_id]


class _Links:
    def plan_url(self, _plan_ref: str) -> str | None:
        return None

    def agent_url(self, _agent_name: str) -> str | None:
        return None

    def commit_url(self, _sha: str) -> str | None:
        return None


def _store(tmp_path: Path, *, with_beads: bool = True) -> SddStore:
    plans = tmp_path / "plans"
    beads = tmp_path / "beads"
    plans.mkdir()
    if with_beads:
        beads.mkdir()
    return SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        beads_dir=beads if with_beads else None,
    )


def _register_project(project_name: str, checkout: Path) -> None:
    project_dir = sase_projects_dir() / project_name
    project_dir.mkdir(parents=True)
    (project_dir / f"{project_name}.sase").write_text(
        f"WORKSPACE_DIR: {checkout}\n",
        encoding="utf-8",
    )


def _write_marker(checkout: Path, *, project_name: str) -> None:
    marker_path = checkout / ".sase" / "checkout.json"
    marker_path.parent.mkdir(parents=True)
    marker_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_name": project_name,
                "project_key": project_name,
                "workspace_num": 3,
                "primary_workspace_dir": str(checkout),
                "registry_path": str(checkout / "registry.json"),
            }
        ),
        encoding="utf-8",
    )


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_git_repo(repo: Path, remote: str) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "checkout", "-B", "main")
    _git(repo, "config", "user.name", "SASE Test")
    _git(repo, "config", "user.email", "sase-test@example.com")
    _git(repo, "remote", "add", "origin", remote)


def _commit_bead(repo: Path, filename: str, subject: str, bead_id: str) -> str:
    (repo / filename).write_text(subject, encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-q", "-m", subject, "-m", f"SASE_BEAD={bead_id}")
    return _git(repo, "rev-parse", "HEAD").stdout.strip().casefold()


def _patch_publication_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    store: SddStore,
    view: _View,
) -> list[tuple[str, tuple[Path, ...], str]]:
    @contextmanager
    def acquired_lock(*_args: object, **_kwargs: object):
        yield True

    monkeypatch.setattr(
        "sase.sdd.plan_refs.workspace_context_for_plan_resolution",
        lambda _root: (store.sdd_dir, 1),
    )
    monkeypatch.setattr("sase.sdd.store.resolve_sdd_store", lambda *_args: store)
    monkeypatch.setattr(
        "sase.sdd._git_contention.store_git_write_lock",
        acquired_lock,
    )
    monkeypatch.setattr(
        "sase.bead.store_locator.open_bead_project_for_beads_dir",
        lambda _root: view,
    )
    monkeypatch.setattr(
        "sase.sdd.hosted_links.hosted_link_resolver",
        lambda *_args, **_kwargs: _Links(),
    )
    monkeypatch.setattr(
        "sase.bead_pages.associations.build_bead_association_index",
        lambda *_args, **_kwargs: BeadAssociationIndex(MappingProxyType({})),
    )
    commits: list[tuple[str, tuple[Path, ...], str]] = []

    def commit_store(
        _store: SddStore,
        message: str,
        **kwargs: object,
    ) -> bool:
        paths = tuple(Path(path) for path in kwargs["paths"])  # type: ignore[index]
        commits.append((message, paths, str(kwargs["push_after_commit"])))
        assert kwargs["auto_commit_type"] == "beads"
        assert kwargs["already_locked"] is True
        return len(commits) == 1

    monkeypatch.setattr("sase.sdd.files.commit_sdd_store_files", commit_store)
    return commits


def test_tagged_commit_publishes_whole_lineage_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    root = Issue("sase-ai", "Published pages", issue_type=IssueType.PLAN)
    phase = Issue(
        "sase-ai.5",
        "Publication",
        issue_type=IssueType.PHASE,
        parent_id=root.id,
    )
    unrelated = Issue("sase-other", "Other", issue_type=IssueType.PLAN)
    commits = _patch_publication_dependencies(
        monkeypatch,
        store,
        _View((root, phase, unrelated)),
    )
    message = "feat: publish\n\nSASE_BEAD=sase-ai.5"

    first = publish_committed_bead_pages(message, primary_root=tmp_path)
    second = publish_committed_bead_pages(message, primary_root=tmp_path)

    assert first.changed and first.committed
    assert not second.changed and not second.committed
    assert commits[0][1] == (store.beads_dir,)
    assert commits == 2 * [
        (
            "chore(beads): sync bead state and pages for sase-ai",
            (store.beads_dir,),
            "async",
        )
    ]
    assert not (store.beads_dir / "pages" / "README.md").exists()
    assert not (store.beads_dir / "pages" / "sase-other").exists()


def test_sidecar_publication_anchors_associations_and_commit_links_to_primary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = tmp_path / "checkout"
    plans = checkout / "sase" / "repos" / "plans"
    beads = checkout / "sase" / "repos" / "beads"
    _init_git_repo(checkout, "git@github.com:sase-org/sase.git")
    _init_git_repo(plans, "git@github.com:sase-org/sase--plans.git")
    _init_git_repo(beads, "git@github.com:sase-org/sase--beads.git")
    _register_project("sase", checkout)
    _write_marker(checkout, project_name="sase")
    with BeadProject.init(beads, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        root = project.create("Published pages", IssueType.PLAN)
        phase = project.create("Publication", IssueType.PHASE, parent_id=root.id)
    phase_id = phase.id
    primary_sha = _commit_bead(
        checkout,
        "primary.txt",
        "feat: primary association",
        phase_id,
    )
    _commit_bead(plans, "plan.txt", "docs: sidecar association", phase_id)
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        provider="github",
        remote_url="git@github.com:sase-org/sase--plans.git",
        beads_dir=beads,
        beads_remote_url="git@github.com:sase-org/sase--beads.git",
    )

    @contextmanager
    def acquired_lock(*_args: object, **_kwargs: object):
        yield True

    monkeypatch.setattr("sase.sdd.store.resolve_sdd_store", lambda *_args: store)
    monkeypatch.setattr(
        "sase.sdd._git_contention.store_git_write_lock",
        acquired_lock,
    )
    monkeypatch.setattr(
        "sase.sdd.files.commit_sdd_store_files",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        "sase.core.agent_identity_facade.AgentIdentitySnapshot.current",
        lambda: AgentIdentitySnapshot(AgentOwnerIdentity("alice", "athena")),
    )
    monkeypatch.setattr(
        "sase.bead_pages.associations._build.load_artifact_records",
        lambda _project: (),
    )
    message = f"docs: sidecar association\n\nSASE_BEAD={phase_id}"

    from_primary = publish_committed_bead_pages(message, primary_root=checkout)
    primary_payload = (beads / "pages" / root.id / "README.md").read_text(
        encoding="utf-8"
    )
    from_sidecar = publish_committed_bead_pages(message, primary_root=plans)
    sidecar_payload = (beads / "pages" / root.id / "README.md").read_text(
        encoding="utf-8"
    )

    assert from_primary.error is None
    assert from_sidecar.error is None
    assert sidecar_payload == primary_payload
    assert f"https://github.com/sase-org/sase/commit/{primary_sha}" in sidecar_payload
    assert "feat: primary association" in sidecar_payload
    assert "docs: sidecar association" not in sidecar_payload
    assert "sase--plans/commit/" not in sidecar_payload


def test_missing_sidecar_and_missing_tag_skip_without_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path, with_beads=False)
    monkeypatch.setattr(
        "sase.sdd.plan_refs.workspace_context_for_plan_resolution",
        lambda _root: (store.sdd_dir, 1),
    )
    monkeypatch.setattr("sase.sdd.store.resolve_sdd_store", lambda *_args: store)

    no_tag = publish_committed_bead_pages("feat: no tag", primary_root=tmp_path)
    no_sidecar = publish_committed_bead_pages(
        "feat: tagged\n\nSASE_BEAD=sase-ai.5",
        primary_root=tmp_path,
    )

    assert no_tag.skip_reason == "commit has no SASE_BEAD tag"
    assert no_tag.error is None
    assert no_sidecar.skip_reason == "project has no recorded beads sidecar"
    assert no_sidecar.error is None


def test_rendering_failure_is_captured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _store(tmp_path)
    issue = Issue("sase-ai", "Published pages", issue_type=IssueType.PLAN)
    commits = _patch_publication_dependencies(monkeypatch, store, _View((issue,)))
    monkeypatch.setattr(
        "sase.bead_pages.rendering.render_bead_page_bytes",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("render failed")),
    )

    outcome = publish_committed_bead_pages(
        "feat: tagged\n\nSASE_BEAD=sase-ai",
        primary_root=tmp_path,
    )

    assert outcome.error == "render failed"
    assert not outcome.changed and outcome.committed
    assert commits == [
        (
            "chore(beads): sync bead state and pages for sase-ai",
            (store.beads_dir,),
            "async",
        )
    ]
    assert "Could not publish committed bead pages" in caplog.text


def test_store_health_failure_preserves_changed_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = _store(tmp_path)
    issue = Issue("sase-ai", "Published pages", issue_type=IssueType.PLAN)
    _patch_publication_dependencies(monkeypatch, store, _View((issue,)))
    monkeypatch.setattr(
        "sase.sdd.files.commit_sdd_store_files",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("sidecar is unhealthy")
        ),
    )

    outcome = publish_committed_bead_pages(
        "feat: tagged\n\nSASE_BEAD=sase-ai",
        primary_root=tmp_path,
    )

    assert outcome.changed and not outcome.committed
    assert outcome.error == "sidecar is unhealthy"
    assert "Could not publish committed bead pages" in caplog.text


def test_workflow_checkpoints_best_effort_publication_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cp = CommitCheckpoint(
        method="create_commit",
        payload={"message": "feat: tagged\n\nSASE_BEAD=sase-ai.5"},
        cwd=str(tmp_path),
    )
    calls: list[str] = []
    monkeypatch.setattr(
        "sase.bead_pages.publication.publish_committed_bead_pages",
        lambda message, **_kwargs: (
            calls.append(message)
            or type("_Outcome", (), {"error": "sidecar unhealthy"})()
        ),
    )
    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.refresh_committed_plan_header",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "sase.workflows.commit.workflow.checkpoint_save",
        lambda _cp: None,
    )
    workflow = CommitWorkflow(cp.payload, cp.method)

    assert workflow._run_agent_publication_step(cp) == RunResult.OK
    assert workflow._run_agent_publication_step(cp) == RunResult.OK
    assert calls == [cp.payload["message"]]
    assert cp.completed_steps == ["publish_bead_pages"]


def test_workflow_ignores_unexpected_publication_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cp = CommitCheckpoint(
        method="create_commit",
        payload={"message": "feat: tagged\n\nSASE_BEAD=sase-ai.5"},
        cwd=str(tmp_path),
    )
    monkeypatch.setattr(
        "sase.bead_pages.publication.publish_committed_bead_pages",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.refresh_committed_plan_header",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "sase.workflows.commit.workflow.checkpoint_save",
        lambda _cp: None,
    )

    result = CommitWorkflow(cp.payload, cp.method)._run_agent_publication_step(cp)

    assert result == RunResult.OK
    assert cp.completed_steps == ["publish_bead_pages"]
