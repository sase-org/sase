"""Claimed-workspace orchestration tests for :mod:`sase.ace.revert_agent`.

These cover the property that the Agents-tab revert flow claims a *fresh*
short-lived workspace for each preview/execute, prepares it on the ChangeSpec
branch, and releases the claim on every completion and failure path — never
reusing (or blocking on) the directory the agent originally ran in.
"""

from __future__ import annotations

from pathlib import Path

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
from tests.ace._revert_agent_helpers import (
    _commit,
    _git,
    _init_repo,
    _msg,
)
from tests.ace._revert_agent_workspace_helpers import (
    _ClaimRecorder,
    _init_on_branch_cl,
)


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
