"""Dispatch bead handling for pinned siblings without close rights."""

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


def test_dispatch_pinned_sibling_without_bead_stays_unflagged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.finalizers.commit_dispatch as dispatch_mod

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

    sibling = DirtyRepo(
        name="sase-core",
        path=str(sibling_dir),
        changed_files=("lib.rs",),
        kind="sibling",  # type: ignore[arg-type]
    )
    # No bead fields: no assigned bead, so the sibling stitch keeps no -B.
    decisions = {
        repository_decision_id(sibling): {
            "action": "commit",
            "message": "feat: core",
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

    dispatch_commit_decisions(
        (sibling,),
        decisions,
        state=_state(str(primary), artifacts),
        context=FinalizerExecutionContext(
            artifacts_dir=str(artifacts),
            plan_digest="sha256:test",
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

    assert bead_actions["sase-core"] is None


def test_unpushed_resume_downgrades_pinned_sibling_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.finalizers.commit_unpushed_resume as resume_mod
    from sase.finalizers.commit_unpushed_resume import (
        resume_unpushed_already_clean_repos,
    )

    primary = tmp_path / "sase"
    primary.mkdir()
    sibling_dir = tmp_path / "core"
    sibling_dir.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "commit_results.json").write_text(
        json.dumps(
            [
                {
                    "cwd": str(sibling_dir),
                    "result": "ok",
                    "commit_sha": "a" * 40,
                    "commit_tree": "d" * 40,
                    "pushed": False,
                }
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        resume_mod,
        "_revision_pins_for_project",
        lambda _project_dir: {"sase-core": "sase-core-revision.txt"},
    )

    sibling = DirtyRepo(
        name="sase-core",
        path=str(sibling_dir),
        changed_files=("lib.rs",),
        kind="sibling",  # type: ignore[arg-type]
    )
    decisions = {
        repository_decision_id(sibling): {
            "action": "commit",
            "message": "feat: core",
            "bead_action": "close",
        },
    }
    resumed_actions: dict[str, Any] = {}

    def resume_runner(
        repo: DirtyRepo, _context: object, **kwargs: Any
    ) -> StitchCommandResult:
        resumed_actions[repo.name] = kwargs.get("bead_action")
        return StitchCommandResult(
            returncode=0, stdout="ok", stderr="", argv=(), message_file=None
        )

    resume_unpushed_already_clean_repos(
        (sibling,),
        decisions=decisions,
        artifacts=artifacts,
        context=FinalizerExecutionContext(
            artifacts_dir=str(artifacts),
            plan_digest="sha256:test",
            assigned_bead_id="sase-x.1",
        ),
        instance_id="commit",
        resume_runner=resume_runner,  # type: ignore[arg-type]
        ledger=None,
        current_result=InvokeResult(content=""),
        project_dir=str(primary),
    )

    assert resumed_actions["sase-core"] == "keep"
