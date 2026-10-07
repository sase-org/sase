"""Pinned-sibling ordering and no-pin dispatch order."""

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


def test_pinned_sibling_bead_action_downgrade_matrix() -> None:
    from sase.finalizers.commit_revision_pin import pinned_sibling_bead_action

    sibling = DirtyRepo(
        name="sase-core",
        path="/tmp/core",
        changed_files=(),
        kind="sibling",  # type: ignore[arg-type]
    )
    main = DirtyRepo(name="main", path="/tmp/sase", changed_files=(), kind="main")
    other = DirtyRepo(
        name="sase-docs",
        path="/tmp/docs",
        changed_files=(),
        kind="sibling",  # type: ignore[arg-type]
    )
    pins = {"sase-core": "sase-core-revision.txt"}

    assert pinned_sibling_bead_action(sibling, "close", pins) == "keep"
    assert pinned_sibling_bead_action(sibling, "keep", pins) == "keep"
    assert pinned_sibling_bead_action(sibling, None, pins) is None
    assert pinned_sibling_bead_action(main, "close", pins) == "close"
    assert pinned_sibling_bead_action(main, None, pins) is None
    assert pinned_sibling_bead_action(other, "close", pins) == "close"
    assert pinned_sibling_bead_action(sibling, "close", {}) == "close"
