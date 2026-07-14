"""Claimed-workspace orchestration tests for :mod:`sase.ace.revert_agent`.

These cover the property that the Agents-tab revert flow claims a *fresh*
short-lived workspace for each preview/execute, prepares it on the ChangeSpec
branch, and releases the claim on every completion and failure path — never
reusing (or blocking on) the directory the agent originally ran in.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import sase.ace.revert_agent_workspace as raw
from sase.ace.revert_agent import (
    BulkRevertIntent,
    RevertIntent,
    RevertTarget,
    execute_agent_revert_intent,
    execute_agents_revert_intent,
    preview_agent_revert_intent,
    preview_agents_revert_intent,
)
from sase.ace.revert_agent_models import RevertRepo
from sase.ace.revert_agent_workspace import (
    REVERT_WORKSPACE_WORKFLOW,
    RevertWorkspaceError,
    _PreparedRevertWorkspace,
)
from sase.linked_repos import record_opened_external_repo
from tests.ace._revert_agent_helpers import (
    _add_bare_origin,
    _commit,
    _git,
    _init_repo,
    _msg,
)


def _init_on_branch_cl(repo: Path, agent: str = "foo", subject: str = "feature") -> str:
    """Init a repo, branch ``cl``, and add one AGENT-tagged commit on it."""
    _init_repo(repo)
    _git(repo, "checkout", "-q", "-b", "cl")
    return _commit(repo, _msg(subject, agent), {f"{subject}.txt": f"{subject}\n"})


class _ClaimRecorder:
    """Records claim/release calls and hands out a fixed workspace number."""

    def __init__(self, workspace_num: int = 11) -> None:
        self.workspace_num = workspace_num
        self.claims: list[tuple[str, str, str | None]] = []
        self.releases: list[tuple[str, int, str | None, str | None]] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_claim(
            project_file: str,
            workflow: str,
            pid: int,
            cl_name: str | None = None,
            **_: object,
        ) -> int:
            self.claims.append((project_file, workflow, cl_name))
            return self.workspace_num

        def fake_release(
            project_file: str,
            workspace_num: int,
            workflow: str | None = None,
            cl_name: str | None = None,
        ) -> object:
            self.releases.append((project_file, workspace_num, workflow, cl_name))
            return SimpleNamespace(success=True, error=None)

        monkeypatch.setattr(raw, "claim_next_axe_workspace", fake_claim)
        monkeypatch.setattr(raw, "release_workspace", fake_release)


def _intent(project_file: Path, *, agent: str = "foo") -> RevertIntent:
    return RevertIntent(
        project_file=str(project_file),
        project_basename="p",
        cl_name="cl",
        agent_name=agent,
    )


# ---------------------------------------------------------------------------
# Single-agent orchestration (prepare seam stubbed with a real claimed repo)
# ---------------------------------------------------------------------------


def test_preview_claims_and_releases_and_ignores_dirty_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The directory the agent ran in is dirty; it must never be inspected.
    original = tmp_path / "original_ws"
    _init_on_branch_cl(original)
    (original / "unrelated.txt").write_text("dirty\n", encoding="utf-8")

    claimed = tmp_path / "claimed_ws"
    _init_on_branch_cl(claimed)

    recorder = _ClaimRecorder(workspace_num=11)
    recorder.install(monkeypatch)
    monkeypatch.setattr(
        raw,
        "_prepare_revert_workspace",
        lambda intent, num: _PreparedRevertWorkspace(
            workspace_num=num,
            primary_dir=str(claimed),
            repos=(RevertRepo("primary", str(claimed), is_primary=True),),
        ),
    )

    project_file = tmp_path / "proj.sase"
    preview = preview_agent_revert_intent(_intent(project_file))

    assert preview.ok, preview.error
    # Preview operated on the claimed checkout, not the dirty original.
    assert preview.repos[0].workspace_dir == str(claimed)
    assert _git(original, "status", "--porcelain").strip() != ""  # still dirty
    # Claim + release happened with the revert-specific workflow label.
    assert recorder.claims == [(str(project_file), REVERT_WORKSPACE_WORKFLOW, "cl")]
    assert recorder.releases == [
        (str(project_file), 11, REVERT_WORKSPACE_WORKFLOW, "cl")
    ]


def test_execute_reverts_in_claimed_workspace_leaving_original_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = tmp_path / "original_ws"
    _init_on_branch_cl(original)
    claimed = tmp_path / "claimed_ws"
    _init_on_branch_cl(claimed)

    recorder = _ClaimRecorder(workspace_num=12)
    recorder.install(monkeypatch)
    monkeypatch.setattr(
        raw,
        "_prepare_revert_workspace",
        lambda intent, num: _PreparedRevertWorkspace(
            workspace_num=num,
            primary_dir=str(claimed),
            repos=(RevertRepo("primary", str(claimed), is_primary=True),),
        ),
    )

    project_file = tmp_path / "proj.sase"
    intent = _intent(project_file)
    preview = preview_agent_revert_intent(intent)
    assert preview.ok

    original_head = _git(original, "rev-parse", "HEAD").strip()
    result = execute_agent_revert_intent(preview, intent)

    assert result.success, result.message
    # The revert landed in the claimed checkout...
    assert not (claimed / "feature.txt").exists()
    # ...and the original agent workspace was never touched.
    assert (original / "feature.txt").exists()
    assert _git(original, "rev-parse", "HEAD").strip() == original_head
    # Two claims (preview + execute), two releases.
    assert len(recorder.claims) == 2
    assert len(recorder.releases) == 2
    assert recorder.releases[-1] == (
        str(project_file),
        12,
        REVERT_WORKSPACE_WORKFLOW,
        "cl",
    )


def test_release_on_preparation_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _ClaimRecorder(workspace_num=11)
    recorder.install(monkeypatch)

    def boom(intent: object, num: int) -> _PreparedRevertWorkspace:
        raise RevertWorkspaceError("could not materialize")

    monkeypatch.setattr(raw, "_prepare_revert_workspace", boom)

    preview = preview_agent_revert_intent(_intent(tmp_path / "proj.sase"))

    assert not preview.ok
    assert preview.error is not None and "could not materialize" in preview.error
    # The claim was released even though preparation raised.
    assert len(recorder.releases) == 1


def test_release_on_preview_with_no_commits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claimed = tmp_path / "claimed_ws"
    _init_on_branch_cl(claimed, agent="someone-else")  # no "foo" commits

    recorder = _ClaimRecorder()
    recorder.install(monkeypatch)
    monkeypatch.setattr(
        raw,
        "_prepare_revert_workspace",
        lambda intent, num: _PreparedRevertWorkspace(
            workspace_num=num,
            primary_dir=str(claimed),
            repos=(RevertRepo("primary", str(claimed), is_primary=True),),
        ),
    )

    preview = preview_agent_revert_intent(_intent(tmp_path / "proj.sase"))

    assert not preview.ok  # no commits tagged for "foo"
    assert len(recorder.releases) == 1


def test_release_on_execute_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A later non-foo commit diverges the file so reverting foo conflicts.
    claimed = tmp_path / "claimed_ws"
    _init_repo(claimed)
    _git(claimed, "checkout", "-q", "-b", "cl")
    _commit(claimed, _msg("v1", "foo"), {"file.txt": "v1\n"})
    _commit(claimed, _msg("v2", "foo"), {"file.txt": "v2\n"})
    _commit(claimed, _msg("v3", "bar"), {"file.txt": "v3\n"})

    recorder = _ClaimRecorder()
    recorder.install(monkeypatch)
    monkeypatch.setattr(
        raw,
        "_prepare_revert_workspace",
        lambda intent, num: _PreparedRevertWorkspace(
            workspace_num=num,
            primary_dir=str(claimed),
            repos=(RevertRepo("primary", str(claimed), is_primary=True),),
        ),
    )

    project_file = tmp_path / "proj.sase"
    intent = _intent(project_file)
    preview = preview_agent_revert_intent(intent)
    assert preview.ok
    head_before = _git(claimed, "rev-parse", "HEAD").strip()

    result = execute_agent_revert_intent(preview, intent)

    assert not result.success
    assert _git(claimed, "rev-parse", "HEAD").strip() == head_before  # rolled back
    # Preview + execute each claimed and released.
    assert len(recorder.claims) == 2
    assert len(recorder.releases) == 2


def test_claim_failure_returns_error_without_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    released: list[object] = []

    def fail_claim(*_a: object, **_k: object) -> int:
        raise raw.WorkspaceClaimError("all workspaces busy")

    monkeypatch.setattr(raw, "claim_next_axe_workspace", fail_claim)
    monkeypatch.setattr(raw, "release_workspace", lambda *a, **k: released.append(a))

    preview = preview_agent_revert_intent(_intent(tmp_path / "proj.sase"))

    assert not preview.ok
    assert preview.error is not None and "all workspaces busy" in preview.error
    # Nothing was claimed, so nothing is released.
    assert released == []


# ---------------------------------------------------------------------------
# Bulk orchestration
# ---------------------------------------------------------------------------


def test_bulk_preview_and_execute_use_one_claim_each(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claimed = tmp_path / "claimed_ws"
    _init_repo(claimed)
    _git(claimed, "checkout", "-q", "-b", "cl")
    _commit(claimed, _msg("foo feature", "foo"), {"foo.txt": "foo\n"})
    _commit(claimed, _msg("bar feature", "bar"), {"bar.txt": "bar\n"})

    recorder = _ClaimRecorder(workspace_num=13)
    recorder.install(monkeypatch)
    monkeypatch.setattr(
        raw,
        "_prepare_revert_workspace",
        lambda intent, num: _PreparedRevertWorkspace(
            workspace_num=num,
            primary_dir=str(claimed),
            repos=(RevertRepo("primary", str(claimed), is_primary=True),),
        ),
    )

    project_file = tmp_path / "proj.sase"
    intent = BulkRevertIntent(
        project_file=str(project_file),
        project_basename="p",
        cl_name="cl",
        targets=(
            RevertTarget("foo", "foo", str(claimed)),
            RevertTarget("bar", "bar", str(claimed)),
        ),
    )

    preview = preview_agents_revert_intent(intent)
    assert preview.ok
    assert preview.commit_count == 2
    assert set(preview.matched_target_names) == {"foo", "bar"}

    head_before = _git(claimed, "rev-parse", "HEAD").strip()
    result = execute_agents_revert_intent(preview, intent)

    assert result.success, result.message
    assert not (claimed / "foo.txt").exists()
    assert not (claimed / "bar.txt").exists()
    # One revert commit for the combined set.
    assert _git(claimed, "rev-list", "--count", f"{head_before}..HEAD").strip() == "1"
    # Exactly one claim/release for preview and one for execute, all on #13.
    assert [c[0] for c in recorder.claims] == [str(project_file), str(project_file)]
    assert {r[1] for r in recorder.releases} == {13}
    assert len(recorder.releases) == 2


# ---------------------------------------------------------------------------
# Real preparation (materialize + branch checkout + linked repos)
# ---------------------------------------------------------------------------


def _install_prepare_seams(
    monkeypatch: pytest.MonkeyPatch,
    *,
    primary_dir: Path,
    claimed_primary: Path,
    linked_resolution: object,
    captured: dict[str, int],
) -> None:
    # Force the bare-git provider so the synthetic local repos (which have no
    # ``origin`` remote) resolve without a VCS plugin lookup.
    monkeypatch.setenv("SASE_VCS_PROVIDER", "bare_git")
    monkeypatch.setattr(raw, "parse_workspace_dir", lambda pf: str(primary_dir))
    monkeypatch.setattr(raw, "detect_vcs_family", lambda d: "git")

    def fake_ensure(primary: str, num: int, **_: object) -> str:
        captured["primary_num"] = num
        return str(claimed_primary)

    def fake_resolve_linked(
        *, project_file: str, workspace_dir: str, workspace_num: int, materialize: bool
    ) -> object:
        captured["linked_num"] = workspace_num
        return linked_resolution

    monkeypatch.setattr(raw, "ensure_workspace_checkout", fake_ensure)
    monkeypatch.setattr(raw, "resolve_linked_repos_for_project", fake_resolve_linked)


def test_prepare_materializes_and_prepares_linked_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary_origin = tmp_path / "primary_origin"
    primary_origin.mkdir()
    claimed_primary = tmp_path / "claimed_primary"
    _init_on_branch_cl(claimed_primary, agent="foo", subject="primary")
    claimed_linked = tmp_path / "claimed_linked"
    _init_on_branch_cl(claimed_linked, agent="foo", subject="linked")

    captured: dict[str, int] = {}
    linked_resolution = SimpleNamespace(
        repos=[
            SimpleNamespace(
                name="sase-core",
                workspace_dir=str(claimed_linked),
                primary_dir=str(primary_origin),
            )
        ]
    )
    _install_prepare_seams(
        monkeypatch,
        primary_dir=primary_origin,
        claimed_primary=claimed_primary,
        linked_resolution=linked_resolution,
        captured=captured,
    )

    recorder = _ClaimRecorder(workspace_num=21)
    recorder.install(monkeypatch)

    intent = RevertIntent(
        project_file=str(tmp_path / "proj.sase"),
        project_basename="p",
        cl_name="cl",
        agent_name="foo",
        linked_repo_names=("sase-core",),
    )
    preview = preview_agent_revert_intent(intent)

    assert preview.ok, preview.error
    assert [r.repo_label for r in preview.revertable_repos] == ["primary", "sase-core"]
    assert preview.commit_count == 2
    # Primary and linked repos were materialized for the *same* claimed number.
    assert captured["primary_num"] == 21
    assert captured["linked_num"] == 21
    assert len(recorder.releases) == 1


def test_project_scoped_preview_uses_default_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary_origin = tmp_path / "primary_origin"
    primary_origin.mkdir()
    claimed_primary = tmp_path / "claimed_primary"
    _init_repo(claimed_primary)
    tagged_sha = _commit(
        claimed_primary,
        _msg("project feature", "foo"),
        {"project.txt": "project\n"},
    )
    remote = tmp_path / "remote.git"
    _add_bare_origin(claimed_primary, remote)
    _git(claimed_primary, "push", "-q", "-u", "origin", "main")

    captured: dict[str, int] = {}
    _install_prepare_seams(
        monkeypatch,
        primary_dir=primary_origin,
        claimed_primary=claimed_primary,
        linked_resolution=SimpleNamespace(repos=[]),
        captured=captured,
    )
    recorder = _ClaimRecorder(workspace_num=25)
    recorder.install(monkeypatch)

    project_name = "gh_example__project"
    preview = preview_agent_revert_intent(
        RevertIntent(
            project_file=str(tmp_path / project_name / f"{project_name}.sase"),
            project_basename=project_name,
            cl_name=project_name,
            agent_name="foo",
            is_project_scoped=True,
        )
    )

    assert preview.ok, preview.error
    assert [commit.full_sha for commit in preview.commits] == [tagged_sha]
    assert _git(claimed_primary, "branch", "--show-current").strip() == "main"
    assert project_name not in _git(claimed_primary, "branch", "--list")
    assert captured["primary_num"] == 25
    assert len(recorder.releases) == 1


def test_project_scoped_linked_repo_uses_default_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary_origin = tmp_path / "primary_origin"
    primary_origin.mkdir()
    claimed_primary = tmp_path / "claimed_primary"
    _init_repo(claimed_primary)
    _commit(
        claimed_primary,
        _msg("primary project feature", "foo"),
        {"primary.txt": "primary\n"},
    )
    claimed_linked = tmp_path / "claimed_linked"
    _init_repo(claimed_linked)
    _commit(
        claimed_linked,
        _msg("linked project feature", "foo"),
        {"linked.txt": "linked\n"},
    )

    captured: dict[str, int] = {}
    linked_resolution = SimpleNamespace(
        repos=[
            SimpleNamespace(
                name="sase-core",
                workspace_dir=str(claimed_linked),
                primary_dir=str(primary_origin),
            )
        ]
    )
    _install_prepare_seams(
        monkeypatch,
        primary_dir=primary_origin,
        claimed_primary=claimed_primary,
        linked_resolution=linked_resolution,
        captured=captured,
    )
    recorder = _ClaimRecorder(workspace_num=26)
    recorder.install(monkeypatch)

    project_name = "gh_example__project"
    preview = preview_agent_revert_intent(
        RevertIntent(
            project_file=str(tmp_path / project_name / f"{project_name}.sase"),
            project_basename=project_name,
            cl_name=project_name,
            agent_name="foo",
            is_project_scoped=True,
            linked_repo_names=("sase-core",),
        )
    )

    assert preview.ok, preview.error
    assert [repo.repo_label for repo in preview.revertable_repos] == [
        "primary",
        "sase-core",
    ]
    assert preview.blocked_repos == ()
    assert preview.commit_count == 2
    assert _git(claimed_linked, "branch", "--show-current").strip() == "main"
    assert len(recorder.releases) == 1


def test_project_scoped_preview_syncs_stale_reused_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publisher = tmp_path / "publisher"
    _init_repo(publisher)
    remote = tmp_path / "remote.git"
    _add_bare_origin(publisher, remote)
    _git(publisher, "push", "-q", "-u", "origin", "main")

    claimed_primary = tmp_path / "claimed_primary"
    shutil.copytree(publisher, claimed_primary)
    stale_head = _git(claimed_primary, "rev-parse", "HEAD").strip()
    tagged_sha = _commit(
        publisher,
        _msg("new remote project feature", "foo"),
        {"remote.txt": "remote\n"},
    )
    _git(publisher, "push", "-q", "origin", "main")
    assert stale_head != tagged_sha

    primary_origin = tmp_path / "primary_origin"
    primary_origin.mkdir()
    captured: dict[str, int] = {}
    _install_prepare_seams(
        monkeypatch,
        primary_dir=primary_origin,
        claimed_primary=claimed_primary,
        linked_resolution=SimpleNamespace(repos=[]),
        captured=captured,
    )
    recorder = _ClaimRecorder(workspace_num=27)
    recorder.install(monkeypatch)

    project_name = "gh_example__project"
    preview = preview_agent_revert_intent(
        RevertIntent(
            project_file=str(tmp_path / project_name / f"{project_name}.sase"),
            project_basename=project_name,
            cl_name=project_name,
            agent_name="foo",
            is_project_scoped=True,
        )
    )

    assert preview.ok, preview.error
    assert [commit.full_sha for commit in preview.commits] == [tagged_sha]
    assert _git(claimed_primary, "rev-parse", "HEAD").strip() == tagged_sha
    assert len(recorder.releases) == 1


def test_project_scoped_preview_tolerates_missing_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary_origin = tmp_path / "primary_origin"
    primary_origin.mkdir()
    claimed_primary = tmp_path / "claimed_primary"
    _init_repo(claimed_primary)
    tagged_sha = _commit(
        claimed_primary,
        _msg("local project feature", "foo"),
        {"local.txt": "local\n"},
    )

    captured: dict[str, int] = {}
    _install_prepare_seams(
        monkeypatch,
        primary_dir=primary_origin,
        claimed_primary=claimed_primary,
        linked_resolution=SimpleNamespace(repos=[]),
        captured=captured,
    )
    recorder = _ClaimRecorder(workspace_num=28)
    recorder.install(monkeypatch)

    project_name = "gh_example__project"
    preview = preview_agent_revert_intent(
        RevertIntent(
            project_file=str(tmp_path / project_name / f"{project_name}.sase"),
            project_basename=project_name,
            cl_name=project_name,
            agent_name="foo",
            is_project_scoped=True,
        )
    )

    assert preview.ok, preview.error
    assert [commit.full_sha for commit in preview.commits] == [tagged_sha]
    assert _git(claimed_primary, "remote").strip() == ""
    assert len(recorder.releases) == 1


def test_prepare_loads_external_markers_and_reuses_clone_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary_origin = tmp_path / "primary_origin"
    primary_origin.mkdir()
    claimed_primary = tmp_path / "claimed_primary"
    _init_on_branch_cl(claimed_primary, agent="someone-else", subject="primary")
    external = tmp_path / "external" / "gh" / "pallets" / "click"
    _init_repo(external)
    (external / "README.md").write_text("dirty\n", encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    record_opened_external_repo(
        "gh:pallets/click",
        str(external),
        reason="port parser fix",
    )

    captured: dict[str, int] = {}
    _install_prepare_seams(
        monkeypatch,
        primary_dir=primary_origin,
        claimed_primary=claimed_primary,
        linked_resolution=SimpleNamespace(repos=[]),
        captured=captured,
    )
    recorder = _ClaimRecorder(workspace_num=24)
    recorder.install(monkeypatch)

    preview = preview_agent_revert_intent(
        RevertIntent(
            project_file=str(tmp_path / "proj.sase"),
            project_basename="p",
            cl_name="cl",
            agent_name="foo",
            external_artifact_dirs=(("foo", str(artifacts)),),
        )
    )

    assert preview.ok, preview.error
    assert preview.commit_count == 0
    assert len(preview.revertable_repos) == 1
    plan = preview.revertable_repos[0]
    assert plan.repo_label == "gh:pallets/click"
    assert plan.repo_kind == "external"
    assert plan.workspace_dir == str(external)
    assert plan.source_agent_names == ("foo",)
    assert plan.discard_local_changes is True
    assert captured["primary_num"] == 24
    assert len(recorder.releases) == 1


def test_prepare_blocks_linked_repo_missing_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary_origin = tmp_path / "primary_origin"
    primary_origin.mkdir()
    claimed_primary = tmp_path / "claimed_primary"
    _init_on_branch_cl(claimed_primary, agent="foo", subject="primary")
    # Linked repo has no "cl" branch and no origin, so checkout cl fails.
    claimed_linked = tmp_path / "claimed_linked"
    _init_repo(claimed_linked)

    captured: dict[str, int] = {}
    linked_resolution = SimpleNamespace(
        repos=[
            SimpleNamespace(
                name="sase-core",
                workspace_dir=str(claimed_linked),
                primary_dir=str(primary_origin),
            )
        ]
    )
    _install_prepare_seams(
        monkeypatch,
        primary_dir=primary_origin,
        claimed_primary=claimed_primary,
        linked_resolution=linked_resolution,
        captured=captured,
    )

    recorder = _ClaimRecorder(workspace_num=22)
    recorder.install(monkeypatch)

    intent = RevertIntent(
        project_file=str(tmp_path / "proj.sase"),
        project_basename="p",
        cl_name="cl",
        agent_name="foo",
        linked_repo_names=("sase-core",),
    )
    preview = preview_agent_revert_intent(intent)

    # Primary still revertable; the linked repo is reported blocked rather than
    # silently falling back to a stale checkout.
    assert preview.ok, preview.error
    assert [r.repo_label for r in preview.revertable_repos] == ["primary"]
    assert [r.repo_label for r in preview.blocked_repos] == ["sase-core"]
    blocked = preview.blocked_repos[0]
    assert blocked.blocked_reason is not None
    assert "check out branch" in blocked.blocked_reason
    assert len(recorder.releases) == 1


def test_prepare_raises_when_primary_branch_checkout_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary_origin = tmp_path / "primary_origin"
    primary_origin.mkdir()
    # Claimed primary lacks the "cl" branch (only main, no origin) -> checkout
    # fails -> preparation raises and the claim is still released.
    claimed_primary = tmp_path / "claimed_primary"
    _init_repo(claimed_primary)

    captured: dict[str, int] = {}
    _install_prepare_seams(
        monkeypatch,
        primary_dir=primary_origin,
        claimed_primary=claimed_primary,
        linked_resolution=SimpleNamespace(repos=[]),
        captured=captured,
    )

    recorder = _ClaimRecorder(workspace_num=23)
    recorder.install(monkeypatch)

    intent = RevertIntent(
        project_file=str(tmp_path / "proj.sase"),
        project_basename="p",
        cl_name="cl",
        agent_name="foo",
    )
    preview = preview_agent_revert_intent(intent)

    assert not preview.ok
    assert preview.error is not None and "check out branch" in preview.error
    assert len(recorder.releases) == 1
