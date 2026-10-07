"""Dispatch pin-follow with bead-action downgrade coverage."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from sase.finalizers.commit_declaration import repository_decision_id
from sase.finalizers.commit_dispatch import dispatch_commit_decisions
from sase.finalizers.commit_types import StitchCommandResult
from sase.finalizers.executor import FinalizerExecutionContext
from sase.finalizers.ledger import InstanceLedger
from sase.finalizers.reconciliation import PreparedCommitDirtyState
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState
from sase.llm_provider.types import InvokeResult


def _assert_bead_action_allowed(
    repo_name: str, bead_action: Any, assigned_bead_id: str
) -> None:
    """Fail the same way production does if `-B` is stripped or mis-assigned."""

    from sase.core.bead_action_facade import (
        bead_action_wire_schema_version,
        decide_bead_action,
    )

    if repo_name == "sase-core":
        scope, primary_identified = "linked", False
    else:
        scope, primary_identified = "primary", True
    request: dict[str, Any] = {
        "schema_version": bead_action_wire_schema_version(),
        "commit_method": "create_commit",
        "repository_scope": scope,
        "primary_repository_identified": primary_identified,
        "assigned_bead_id": assigned_bead_id,
    }
    if bead_action is not None:
        request["bead_action"] = bead_action
    if bead_action == "close":
        request["bead_status"] = "in_progress"
    decide_bead_action(request)


def test_dispatch_commits_pinned_sibling_first_and_follows_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.finalizers.commit_dispatch as dispatch_mod
    import sase.finalizers.commit_revision_pin as pin_mod

    primary = tmp_path / "sase"
    primary.mkdir()
    sibling_dir = tmp_path / "core"
    sibling_dir.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (primary / "sase-core-revision.txt").write_text("b" * 40 + "\n", encoding="utf-8")

    monkeypatch.setattr(
        dispatch_mod,
        "_revision_pins_for_project",
        lambda _project_dir: {"sase-core": "sase-core-revision.txt"},
    )
    monkeypatch.setattr(
        pin_mod, "_sha_reachable_from_default_branch", lambda *a, **k: True
    )
    monkeypatch.setattr(pin_mod, "_pin_is_ancestor", lambda *a, **k: True)

    main = DirtyRepo(
        name="main", path=str(primary), changed_files=("app.py",), kind="main"
    )
    sibling = DirtyRepo(
        name="sase-core",
        path=str(sibling_dir),
        changed_files=("lib.rs",),
        kind="sibling",  # type: ignore[arg-type]
    )
    assigned_bead_id = "sase-x.1"
    decisions = {
        repository_decision_id(main): {
            "action": "commit",
            "message": "feat: x",
            "bead_action": "close",
        },
        repository_decision_id(sibling): {
            "action": "commit",
            "message": "feat: core",
            # The agent declares close everywhere; dispatch must downgrade
            # the pinned sibling to keep (close is primary-only).
            "bead_action": "close",
        },
    }
    order: list[str] = []
    bead_actions: dict[str, Any] = {}

    def stitch_runner(
        repo: DirtyRepo,
        _message: str,
        _excludes: Sequence[str],
        _context: object,
        **kwargs: Any,
    ) -> StitchCommandResult:
        order.append(repo.name)
        bead_actions[repo.name] = kwargs.get("bead_action")
        _assert_bead_action_allowed(
            repo.name, kwargs.get("bead_action"), assigned_bead_id
        )
        markers = []
        try:
            markers = json.loads(
                (artifacts / "commit_results.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            markers = []
        sha = "a" * 40 if repo.name == "sase-core" else "c" * 40
        markers.append(
            {
                "cwd": repo.path,
                "result": "ok",
                "commit_sha": sha,
                "commit_tree": "d" * 40,
            }
        )
        (artifacts / "commit_results.json").write_text(
            json.dumps(markers), encoding="utf-8"
        )
        return StitchCommandResult(
            returncode=0, stdout="ok", stderr="", argv=(), message_file=None
        )

    def _state(_project_dir: str, _artifacts: Any) -> PreparedCommitDirtyState:
        return PreparedCommitDirtyState(
            dirty_state=DirtyState(project_dir=str(primary), repos=(), details="clean")
        )

    result = dispatch_commit_decisions(
        (main, sibling),
        decisions,
        state=_state(str(primary), artifacts),
        context=FinalizerExecutionContext(
            artifacts_dir=str(artifacts),
            plan_digest="sha256:test",
            assigned_bead_id=assigned_bead_id,
        ),
        instance_id="commit",
        artifacts=artifacts,
        project_dir=str(primary),
        provider=None,
        invoke_result=InvokeResult(content=""),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        options=None,
        stitch_runner=stitch_runner,  # type: ignore[arg-type]
        resume_runner=stitch_runner,  # type: ignore[arg-type]
        ledger=InstanceLedger(instance_id="commit", max_attempts=4),
        prepare_dirty_state=_state,  # type: ignore[arg-type]
        protected_path_resolver=lambda _artifacts, _path: (),
        unexpected_path_resolver=lambda _path, _protected: [],
        baseline_record_resolver=lambda _artifacts, _path: None,
    )

    assert order[0] == "sase-core"
    assert order[-1] == "main"
    # Only the primary stitch may close the bead; the sibling's declared
    # close is downgraded to keep (the policy helper above rejects close
    # on a linked repo, so pass-through would fail this test).
    assert bead_actions["sase-core"] == "keep"
    assert bead_actions["main"] == "close"
    kinds = [item.kind for item in result.evidence]
    assert "revision_pin" in kinds
    pin_evidence = next(
        item.value for item in result.evidence if item.kind == "revision_pin"
    )
    assert pin_evidence.startswith("sase-core:sase-core-revision.txt:")
    assert (primary / "sase-core-revision.txt").read_text(encoding="utf-8") == (
        "a" * 40 + "\n"
    )


def test_dispatch_pinned_sibling_only_carries_keep_and_skips_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.finalizers.commit_dispatch as dispatch_mod
    import sase.finalizers.commit_revision_pin as pin_mod

    primary = tmp_path / "sase"
    primary.mkdir()
    sibling_dir = tmp_path / "core"
    sibling_dir.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (primary / "sase-core-revision.txt").write_text("b" * 40 + "\n", encoding="utf-8")

    monkeypatch.setattr(
        dispatch_mod,
        "_revision_pins_for_project",
        lambda _project_dir: {"sase-core": "sase-core-revision.txt"},
    )
    monkeypatch.setattr(
        pin_mod, "_sha_reachable_from_default_branch", lambda *a, **k: True
    )
    monkeypatch.setattr(pin_mod, "_pin_is_ancestor", lambda *a, **k: True)

    sibling = DirtyRepo(
        name="sase-core",
        path=str(sibling_dir),
        changed_files=("lib.rs",),
        kind="sibling",  # type: ignore[arg-type]
    )
    assigned_bead_id = "sase-x.1"
    decisions = {
        repository_decision_id(sibling): {
            "action": "commit",
            "message": "feat: core",
            "bead_action": "keep",
        },
    }
    bead_actions: dict[str, Any] = {}

    def stitch_runner(
        repo: DirtyRepo,
        _message: str,
        _excludes: Sequence[str],
        _context: object,
        **kwargs: Any,
    ) -> StitchCommandResult:
        bead_actions[repo.name] = kwargs.get("bead_action")
        _assert_bead_action_allowed(
            repo.name, kwargs.get("bead_action"), assigned_bead_id
        )
        markers = []
        try:
            markers = json.loads(
                (artifacts / "commit_results.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            markers = []
        markers.append(
            {
                "cwd": repo.path,
                "result": "ok",
                "commit_sha": "a" * 40,
                "commit_tree": "d" * 40,
            }
        )
        (artifacts / "commit_results.json").write_text(
            json.dumps(markers), encoding="utf-8"
        )
        return StitchCommandResult(
            returncode=0, stdout="ok", stderr="", argv=(), message_file=None
        )

    def _state(_project_dir: str, _artifacts: Any) -> PreparedCommitDirtyState:
        return PreparedCommitDirtyState(
            dirty_state=DirtyState(project_dir=str(primary), repos=(), details="clean")
        )

    result = dispatch_commit_decisions(
        (sibling,),
        decisions,
        state=_state(str(primary), artifacts),
        context=FinalizerExecutionContext(
            artifacts_dir=str(artifacts),
            plan_digest="sha256:test",
            assigned_bead_id=assigned_bead_id,
        ),
        instance_id="commit",
        artifacts=artifacts,
        project_dir=str(primary),
        provider=None,
        invoke_result=InvokeResult(content=""),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        options=None,
        stitch_runner=stitch_runner,  # type: ignore[arg-type]
        resume_runner=stitch_runner,  # type: ignore[arg-type]
        ledger=InstanceLedger(instance_id="commit", max_attempts=4),
        prepare_dirty_state=_state,  # type: ignore[arg-type]
        protected_path_resolver=lambda _artifacts, _path: (),
        unexpected_path_resolver=lambda _path, _protected: [],
        baseline_record_resolver=lambda _artifacts, _path: None,
    )

    assert bead_actions["sase-core"] == "keep"
    kinds = [item.kind for item in result.evidence]
    assert "revision_pin" in kinds
    pin_evidence = next(
        item.value for item in result.evidence if item.kind == "revision_pin"
    )
    assert "skipped" in pin_evidence
    assert any(item.code == "revision_pin_skipped" for item in result.diagnostics)
