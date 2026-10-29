"""Controller and failed-close coverage for explicit carry execution."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.core.finalizer_wire import FinalizerInstanceResultWire
from sase.finalizers._failed_close_recovery_assess import assess_terminal_failure
from sase.finalizers.commit import BuiltinCommitFinalizerError, StitchCommandResult
from sase.finalizers.commit_carry import (
    CARRY_EVIDENCE_KIND,
    _encode_carry_evidence,
    _parse_coverage_entry,
)
from sase.finalizers.controller_context import pending_instance_ids
from sase.finalizers.declaration import publish_final_context, submit_final_manifest
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult

from .finalizers_carry_test_helpers import (
    CARRY_STAGED_REF,
    attach_inheriting_handoff,
    submit_repository_actions,
)
from .finalizers_protocol_harness_test_helpers import (
    dirty_repo,
    patch_dirty,
    prepare_agent_env,
    run_controller,
)


def _carry_kinds(payload: dict[str, Any]) -> list[str]:
    return [
        item["kind"]
        for instance in payload["instances"]
        for item in instance.get("evidence", [])
    ]


def test_all_carry_reaches_fixed_point_without_commit_hooks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {"repos": (dirty_repo(repo),)}
    patch_dirty(monkeypatch, repo, dirty)
    attach_inheriting_handoff(monkeypatch)
    stitch = MagicMock(return_value=StitchCommandResult(returncode=0, stdout="ok\n"))
    pin = MagicMock(return_value=("pin", None))
    monkeypatch.setattr("sase.finalizers.commit_execution.run_stitch_create", stitch)
    monkeypatch.setattr(
        "sase.finalizers.commit_dispatch._maybe_write_revision_pin", pin
    )

    submit_repository_actions(artifacts, default_action="carry")
    result = run_controller(artifacts)

    assert result.content == "done"
    payload = json.loads((artifacts / "finalizer_result.json").read_text())
    assert payload["status"] == "success"
    assert payload["cycles"] == 1
    assert payload["instances"][0]["status"] == "success"
    evidence = payload["instances"][0]["evidence"]
    carry_item = next(item for item in evidence if item["kind"] == CARRY_EVIDENCE_KIND)
    parsed = _parse_coverage_entry(carry_item)
    assert parsed is not None
    repo_id, digest, staged_ref = parsed
    assert repo_id
    assert digest
    assert staged_ref == CARRY_STAGED_REF
    stitch.assert_not_called()
    pin.assert_not_called()
    assert not (artifacts / "commit_results.json").exists()
    assert dirty["repos"] == (dirty_repo(repo),)


def test_mixed_primary_commit_and_linked_carry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    linked = tmp_path / "linked"
    linked.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    main = dirty_repo(repo, name="main", kind="main")
    sibling = dirty_repo(linked, name="plans", kind="sibling")
    dirty = {"repos": (main, sibling)}
    patch_dirty(monkeypatch, repo, dirty)
    attach_inheriting_handoff(monkeypatch)
    calls: list[str] = []

    def run_stitch(
        repo_arg: DirtyRepo,
        _message: str,
        _excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        calls.append(repo_arg.name)
        dirty["repos"] = tuple(
            item for item in dirty["repos"] if item.path != repo_arg.path
        )
        payload: list[dict[str, str]] = []
        existing = artifacts / "commit_results.json"
        if existing.is_file():
            payload = json.loads(existing.read_text(encoding="utf-8"))
        payload.append(
            {
                "cwd": repo_arg.path,
                "result": "ok",
                "commit_sha": "a" * 40,
                "commit_tree": "b" * 40,
            }
        )
        existing.write_text(json.dumps(payload), encoding="utf-8")
        return StitchCommandResult(returncode=0, stdout="ok\n")

    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_create", run_stitch
    )

    submit_repository_actions(artifacts, {0: "commit", 1: "carry"})
    result = run_controller(artifacts)

    assert result.content == "done"
    assert calls == ["main"]
    payload = json.loads((artifacts / "finalizer_result.json").read_text())
    assert payload["status"] == "success"
    assert payload["cycles"] == 1
    kinds = _carry_kinds(payload)
    assert CARRY_EVIDENCE_KIND in kinds
    assert "commit_sha" in kinds
    markers = json.loads((artifacts / "commit_results.json").read_text())
    assert [item["cwd"] for item in markers] == [str(repo)]
    assert dirty["repos"] == (sibling,)


def test_partial_commit_failure_keeps_carry_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    linked = tmp_path / "linked"
    linked.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {
        "repos": (
            dirty_repo(repo, name="main", kind="main"),
            dirty_repo(linked, name="plans", kind="sibling"),
        )
    }
    patch_dirty(monkeypatch, repo, dirty)
    attach_inheriting_handoff(monkeypatch)

    def fail_stitch(
        repo_arg: DirtyRepo,
        _message: str,
        _excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        return StitchCommandResult(returncode=1, stderr="hook failed\n")

    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_create", fail_stitch
    )
    submit_repository_actions(artifacts, {0: "commit", 1: "carry"})
    with pytest.raises(BuiltinCommitFinalizerError, match="hook failed"):
        run_controller(artifacts)

    payload = json.loads((artifacts / "finalizer_result.json").read_text())
    assert payload["status"] == "failed"
    kinds = _carry_kinds(payload)
    assert CARRY_EVIDENCE_KIND in kinds
    assert "commit_sha" not in kinds
    assert "pushed" not in kinds
    assert not (artifacts / "commit_results.json").exists()


def test_deferral_and_carry_on_different_repos(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    linked = tmp_path / "linked"
    linked.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {
        "repos": (
            dirty_repo(repo, name="main", kind="main"),
            dirty_repo(linked, name="plans", kind="sibling"),
        )
    }
    patch_dirty(monkeypatch, repo, dirty)
    attach_inheriting_handoff(monkeypatch)
    stitch = MagicMock(return_value=StitchCommandResult(returncode=0, stdout="ok\n"))
    monkeypatch.setattr("sase.finalizers.commit_execution.run_stitch_create", stitch)

    from sase.finalizers.plan import resolve_and_persist_finalizer_plan
    from sase.macro.directives import PromptDirectives

    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    publication = publish_final_context(artifacts_dir=str(artifacts))
    manifest = deepcopy(publication.payload["manifest_template"])
    repositories = manifest["payloads"][0]["payload"]["repositories"]
    repositories[0]["action"] = "commit"
    repositories[0]["message"] = "chore(final): defer pending review"
    repositories[1]["action"] = "carry"
    repositories[1].pop("message", None)
    repositories[1].pop("bead_action", None)
    manifest["payloads"][0]["payload"]["deferrals"].append(
        {
            "repo_id": repositories[0]["repo_id"],
            "reason": "unsafe_content",
            "paths": ["src/app.py"],
        }
    )
    submit_final_manifest(manifest, artifacts_dir=str(artifacts))
    result = run_controller(artifacts)

    assert result.content == "done"
    stitch.assert_not_called()
    payload = json.loads((artifacts / "finalizer_result.json").read_text())
    assert payload["status"] == "deferred"
    assert payload["cycles"] == 1
    kinds = _carry_kinds(payload)
    assert CARRY_EVIDENCE_KIND in kinds
    assert "deferred_repo" in kinds


def test_later_finalizer_dirt_is_reobserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    extra = tmp_path / "extra"
    extra.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {"repos": (dirty_repo(repo),)}
    patch_dirty(monkeypatch, repo, dirty)
    attach_inheriting_handoff(monkeypatch)
    stitch = MagicMock(return_value=StitchCommandResult(returncode=0, stdout="ok\n"))
    monkeypatch.setattr("sase.finalizers.commit_execution.run_stitch_create", stitch)

    from sase.finalizers.commit_execution import execute_commit_finalizer

    original = execute_commit_finalizer

    def execute_then_add_dirt(*args: object, **kwargs: object) -> object:
        result = original(*args, **kwargs)
        dirty["repos"] = (
            dirty_repo(repo),
            dirty_repo(extra, name="plans", kind="sibling"),
        )
        return result

    monkeypatch.setattr(
        "sase.finalizers.controller_cycle.execute_commit_finalizer",
        execute_then_add_dirt,
    )
    # Keep the accepted carry declaration so the second cycle reaches the
    # extra-dirty executor check instead of MagicMock declaration recovery.
    monkeypatch.setattr(
        "sase.finalizers.controller_context.final_submission_is_current",
        lambda **_kwargs: True,
    )
    submit_repository_actions(artifacts, default_action="carry")
    with pytest.raises(BuiltinCommitFinalizerError) as exc_info:
        run_controller(artifacts)

    assert exc_info.value.code == "stale_commit_declaration"
    stitch.assert_not_called()


def test_failed_close_excludes_proven_carry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    linked = tmp_path / "linked"
    linked.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {
        "repos": (
            dirty_repo(repo, name="main", kind="main"),
            dirty_repo(linked, name="plans", kind="sibling"),
        )
    }
    patch_dirty(monkeypatch, repo, dirty)
    attach_inheriting_handoff(monkeypatch)
    submit_repository_actions(artifacts, {0: "commit", 1: "carry"})

    def fail_main(
        repo_arg: DirtyRepo,
        _message: str,
        _excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        return StitchCommandResult(returncode=1, stderr="hook failed\n")

    monkeypatch.setattr("sase.finalizers.commit_execution.run_stitch_create", fail_main)
    with pytest.raises(BuiltinCommitFinalizerError):
        run_controller(artifacts)

    assessment = assess_terminal_failure(
        str(artifacts),
        failure_code="stitch_failed",
        failure_message="hook failed",
    )
    assert assessment.should_recover is True
    by_name = {item.repo.name: item for item in assessment.repositories}
    assert by_name["plans"].landed is True
    assert by_name["plans"].detail == "accepted carry"
    assert by_name["main"].landed is False


def test_pending_instance_ids_uses_current_carry_coverage() -> None:
    repo_id = "repo-1"
    digest = "d" * 64
    entries = (
        {
            "instance_id": "commit",
            "provider_ref": "builtin@commit",
        },
    )
    payload = {
        "selected_instances": [
            {
                "instance_id": "commit",
                "trigger": "dirty_repository",
                "submission_required": True,
            }
        ],
        "context": {
            "handoff": {"staged_ref": CARRY_STAGED_REF},
            "obligations": [
                {
                    "obligation_id": repo_id,
                    "kind": "repository",
                    "digest": digest,
                }
            ],
        },
    }
    covered = FinalizerInstanceResultWire(
        instance_id="commit",
        status="success",
        evidence=[
            _encode_carry_evidence(
                repo_id=repo_id,
                digest=digest,
                staged_ref=CARRY_STAGED_REF,
            )
        ],
    )
    assert pending_instance_ids(entries, payload, {"commit": covered}, set()) == ()

    stale = FinalizerInstanceResultWire(
        instance_id="commit",
        status="success",
        evidence=[
            _encode_carry_evidence(
                repo_id=repo_id,
                digest="e" * 64,
                staged_ref=CARRY_STAGED_REF,
            )
        ],
    )
    assert pending_instance_ids(entries, payload, {"commit": stale}, set()) == (
        "commit",
    )

    extra = deepcopy(payload)
    extra["context"]["obligations"].append(
        {
            "obligation_id": "repo-2",
            "kind": "repository",
            "digest": "f" * 64,
        }
    )
    assert pending_instance_ids(entries, extra, {"commit": covered}, set()) == (
        "commit",
    )

    bare_success = FinalizerInstanceResultWire(
        instance_id="commit",
        status="success",
        evidence=[],
    )
    assert pending_instance_ids(entries, payload, {"commit": bare_success}, set()) == (
        "commit",
    )
