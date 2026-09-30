"""Pinned-sibling ordering and end-to-end dispatch pin-follow behavior."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from sase.finalizers.commit_declaration import repository_decision_id
from sase.finalizers.commit_dispatch import dispatch_commit_decisions
from sase.finalizers.commit_revision_pin import (
    order_pinned_siblings_first,
    without_pin_protected,
)
from sase.finalizers.commit_types import StitchCommandResult
from sase.finalizers.executor import FinalizerExecutionContext
from sase.finalizers.ledger import InstanceLedger
from sase.finalizers.reconciliation import PreparedCommitDirtyState
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState
from sase.llm_provider.types import InvokeResult


def _repo(name: str, path: Path, kind: str) -> DirtyRepo:
    return DirtyRepo(
        name=name,
        path=str(path),
        changed_files=("dirty.txt",),
        kind=kind,  # type: ignore[arg-type]
    )


def _decisions(*repos: DirtyRepo) -> dict[str, dict[str, Any]]:
    return {
        repository_decision_id(repo): {"action": "commit", "message": "feat: x"}
        for repo in repos
    }


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


# Ordering.


def test_pinned_sibling_ordered_first(tmp_path: Path) -> None:
    main = _repo("main", tmp_path / "sase", "main")
    sibling = _repo("sase-core", tmp_path / "core", "sibling")
    ordered = order_pinned_siblings_first(
        [main, sibling],
        _decisions(main, sibling),
        pins={"sase-core": "sase-core-revision.txt"},
    )
    assert [repo.name for repo in ordered] == ["sase-core", "main"]


def test_order_unchanged_without_pin(tmp_path: Path) -> None:
    main = _repo("main", tmp_path / "sase", "main")
    sibling = _repo("sase-core", tmp_path / "core", "sibling")
    ordered = order_pinned_siblings_first(
        [main, sibling], _decisions(main, sibling), pins={}
    )
    assert [repo.name for repo in ordered] == ["main", "sase-core"]


def test_order_unchanged_when_sibling_deferred(tmp_path: Path) -> None:
    main = _repo("main", tmp_path / "sase", "main")
    sibling = _repo("sase-core", tmp_path / "core", "sibling")
    decisions = _decisions(main, sibling)
    ordered = order_pinned_siblings_first(
        [main, sibling],
        decisions,
        pins={"sase-core": "sase-core-revision.txt"},
        accepted_deferrals={repository_decision_id(sibling): object()},
    )
    assert [repo.name for repo in ordered] == ["main", "sase-core"]


def test_order_unchanged_without_main_commit(tmp_path: Path) -> None:
    main = _repo("main", tmp_path / "sase", "main")
    sibling = _repo("sase-core", tmp_path / "core", "sibling")
    decisions = {
        repository_decision_id(main): {"action": "defer", "message": ""},
        repository_decision_id(sibling): {"action": "commit", "message": "x"},
    }
    ordered = order_pinned_siblings_first(
        [main, sibling],
        decisions,
        pins={"sase-core": "sase-core-revision.txt"},
    )
    assert [repo.name for repo in ordered] == ["main", "sase-core"]


def test_without_pin_protected_drops_host_pin() -> None:
    assert without_pin_protected(
        ("sase-core-revision.txt", "src/app.py"), "sase-core-revision.txt"
    ) == ("src/app.py",)
    assert without_pin_protected(("src/app.py",), "sase-core-revision.txt") == (
        "src/app.py",
    )


# End-to-end dispatch with a fake primary and a fake pinned sibling.


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
            "bead_action": "keep",
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
    # Only the primary stitch may close the bead; the sibling carries keep.
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


def test_dispatch_keeps_today_order_without_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.finalizers.commit_dispatch as dispatch_mod

    primary = tmp_path / "sase"
    primary.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setattr(
        dispatch_mod, "_revision_pins_for_project", lambda _project_dir: {}
    )

    main = DirtyRepo(
        name="main", path=str(primary), changed_files=("app.py",), kind="main"
    )
    sibling = DirtyRepo(
        name="sase-core",
        path=str(tmp_path / "core"),
        changed_files=("lib.rs",),
        kind="sibling",  # type: ignore[arg-type]
    )
    decisions = _decisions(main, sibling)
    order: list[str] = []

    def stitch_runner(
        repo: DirtyRepo,
        _message: str,
        _excludes: Sequence[str],
        _context: object,
        **kwargs: Any,
    ) -> StitchCommandResult:
        order.append(repo.name)
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
                "commit_sha": "e" * 40,
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

    dispatch_commit_decisions(
        (main, sibling),
        decisions,
        state=_state(str(primary), artifacts),
        context=FinalizerExecutionContext(
            artifacts_dir=str(artifacts), plan_digest="sha256:test"
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

    assert order == ["main", "sase-core"]
