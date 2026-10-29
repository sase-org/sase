"""Prepared-bridge: starter coverage, no-commit satisfaction, host install."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.agent.staged_handoff import write_staged_handoff
from sase.finalizers.commit import BuiltinCommitFinalizerError, StitchCommandResult
from sase.finalizers.commit_carry import CARRY_EVIDENCE_KIND, PREPARED_EVIDENCE_KIND
from sase.finalizers.controller_context import ensure_current_declaration
from sase.finalizers.declaration import (
    FINAL_SUBMISSION_FILENAME,
    publish_final_context,
)
from sase.finalizers.declaration_format import format_context_pretty
from sase.finalizers.declaration_store import FinalizerDeclarationError
from sase.finalizers.prepare import (
    bind_prepared_completion,
    prepare_conditional_completion,
)
from sase.finalizers.prepared_coverage import (
    PREPARED_RESERVATION_PAYLOAD_KEY,
    PreparedStarterCoverage,
    _host_completion_is_installing,
    _reservation_from_staged_payload,
    evaluate_prepared_starter_coverage_for_artifacts,
    prepared_coverage_omits_starter_submission,
)
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState
from sase.llm_provider.types import InvokeResult
from sase.monitor.delivery import HOST_COMPLETION_RECEIPT_FILENAME
from sase.monitor.host_completion_state import install_prepared_declaration

from .finalizer_declaration_channel_test_helpers import (
    prepare_dirty_declaration,
    stub_run_silent_check_catalog,
    valid_manifest,
)
from .finalizers_protocol_harness_test_helpers import (
    dirty_repo,
    patch_dirty as patch_controller_dirty,
    prepare_agent_env,
    run_controller,
)


_STAGED_ID = "123e4567-e89b-12d3-a456-426614174000"
_MONITOR_ID = "monitor-1"
_FINGERPRINT = "sha256:prepared-bridge"
_COMMAND = ["just", "check"]


@pytest.fixture(autouse=True)
def _run_silent_check_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    stub_run_silent_check_catalog(monkeypatch)


def _digest(label: str) -> str:
    return sha256(label.encode()).hexdigest()


def _observation(repo_id: str, *, head_tree: str | None = None) -> dict[str, object]:
    return {
        "repo_id": repo_id,
        "kind": "main",
        "name": "main",
        "head": _digest("head"),
        "head_tree": head_tree or _digest("head-tree"),
        "index_tree": _digest("index-tree"),
        "complete": True,
        "paths": [
            {
                "path": "src/app.py",
                "xy": "M",
                "content_hash": _digest("app"),
                "mode": "100644",
                "kind": "file",
                "protected": False,
                "foreign": False,
            }
        ],
    }


def _reservation() -> dict[str, Any]:
    return {
        "staged_id": _STAGED_ID,
        "monitor_id": _MONITOR_ID,
        "request_fingerprint": _FINGERPRINT,
        "command": list(_COMMAND),
    }


def _stage_monitor(
    monkeypatch: pytest.MonkeyPatch,
    artifacts: Path,
    *,
    prepared_intent_ref: str,
    reservation: dict[str, Any] | None = None,
    kind: str = "monitor",
) -> dict[str, Any]:
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.delenv("SASE_FINALIZER_OWNED_TURN", raising=False)
    monkeypatch.delenv("SASE_NATIVE_HELPER", raising=False)
    payload: dict[str, Any] = {"prepared_intent_ref": prepared_intent_ref}
    if reservation is not None:
        payload[PREPARED_RESERVATION_PAYLOAD_KEY] = reservation
    record = {
        "schema_version": 1,
        "staged_id": _STAGED_ID,
        "kind": kind,
        "created_at": "2026-10-29T12:00:00Z",
        "payload": payload,
        "successor_workspace": "inherit",
        "carry_allowed": False,
        "dirty_obligations_at_stage": [],
    }
    write_staged_handoff(record, artifacts_dir=str(artifacts), command="test stage")
    return record


def _seal_prepared(
    monkeypatch: pytest.MonkeyPatch,
    artifacts: Path,
    *,
    command: list[str] = _COMMAND,
) -> tuple[Any, Any, list[dict[str, object]], str]:
    publication = publish_final_context(artifacts_dir=str(artifacts))
    repo_id = publication.context.obligations[0].obligation_id
    observations = [_observation(repo_id)]
    monkeypatch.setattr(
        "sase.finalizers.prepare.observe_completion_repositories",
        lambda _root: observations,
    )
    prepared = prepare_conditional_completion(
        {
            "success_message": "Required checks passed.",
            "verification": {"command": list(command)},
            "declaration": valid_manifest(publication),
        },
        artifacts_dir=str(artifacts),
    )
    return publication, prepared, observations, repo_id


def _coverage_reason(publication: Any) -> str | None:
    payload = publication.payload["commit_declaration"].get("prepared_coverage")
    if not isinstance(payload, dict):
        return None
    return payload.get("reason")


def _ensure(artifacts: Path) -> InvokeResult:
    return ensure_current_declaration(
        provider=object(),
        invoke_result=InvokeResult(content="provider response"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts),
        options=None,
        original_prompt="test",
    )


def test_reservation_from_staged_payload_parses_and_rejects_malformed() -> None:
    parsed = _reservation_from_staged_payload(
        {PREPARED_RESERVATION_PAYLOAD_KEY: _reservation()}
    )
    assert parsed is not None
    assert parsed["staged_id"] == _STAGED_ID
    assert parsed["command"] == _COMMAND
    assert _reservation_from_staged_payload({}) is None
    with pytest.raises(FinalizerDeclarationError) as exc_info:
        _reservation_from_staged_payload({PREPARED_RESERVATION_PAYLOAD_KEY: "nope"})
    assert exc_info.value.code == "unreadable_prepared_reservation"
    with pytest.raises(FinalizerDeclarationError) as exc_info:
        _reservation_from_staged_payload(
            {PREPARED_RESERVATION_PAYLOAD_KEY: {**_reservation(), "command": []}}
        )
    assert exc_info.value.code == "unreadable_prepared_reservation"


def test_host_completion_receipt_blocks_starter_omit(tmp_path: Path) -> None:
    coverage = PreparedStarterCoverage(
        eligible=True,
        covered_repository_ids=("repo-1",),
        reason=None,
        reasons=(),
    )
    assert prepared_coverage_omits_starter_submission(tmp_path, coverage) is True
    (tmp_path / HOST_COMPLETION_RECEIPT_FILENAME).write_text(
        json.dumps({"status": "finalizing"}),
        encoding="utf-8",
    )
    assert _host_completion_is_installing(tmp_path) is True
    assert prepared_coverage_omits_starter_submission(tmp_path, coverage) is False


def test_reserved_starter_omits_submission_after_handoff_only_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    sealed_publication, prepared, _observations, repo_id = _seal_prepared(
        monkeypatch, tmp_path
    )
    sealed_digest = sealed_publication.context.context_digest
    _stage_monitor(
        monkeypatch,
        tmp_path,
        prepared_intent_ref=prepared.intent_ref,
        reservation=_reservation(),
    )

    publication = publish_final_context()

    assert publication.context.context_digest != sealed_digest
    assert publication.submission_required is False
    assert publication.context.requirements[0].submission_required is False
    coverage = publication.payload["commit_declaration"]["prepared_coverage"]
    assert coverage["eligible"] is True
    assert coverage["covered_repository_ids"] == [repo_id]
    pretty = format_context_pretty(publication.payload)
    assert "Prepared coverage: starter leaves sealed work for host completion" in pretty
    assert "Allowed repository actions: commit" in pretty
    assert (
        "carry"
        not in publication.payload["commit_declaration"]["allowed_repository_actions"]
    )


def test_already_bound_starter_omits_submission_without_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    _sealed, prepared, _observations, repo_id = _seal_prepared(monkeypatch, tmp_path)
    bound = bind_prepared_completion(
        prepared.intent_ref,
        monitor_id=_MONITOR_ID,
        command=_COMMAND,
        request_fingerprint=_FINGERPRINT,
        artifacts_dir=tmp_path,
    )
    assert bound["status"] == "bound"
    _stage_monitor(
        monkeypatch,
        tmp_path,
        prepared_intent_ref=prepared.intent_ref,
    )

    publication = publish_final_context()

    assert publication.submission_required is False
    coverage = publication.payload["commit_declaration"]["prepared_coverage"]
    assert coverage["eligible"] is True
    assert coverage["covered_repository_ids"] == [repo_id]


def test_prepared_without_reservation_does_not_fall_back_to_carry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    _sealed, prepared, _observations, _repo_id = _seal_prepared(monkeypatch, tmp_path)
    _stage_monitor(
        monkeypatch,
        tmp_path,
        prepared_intent_ref=prepared.intent_ref,
    )

    publication = publish_final_context()

    assert publication.submission_required is True
    assert _coverage_reason(publication) == "prepared_intent_requires_reservation"
    recovery_calls: list[bool] = []
    monkeypatch.setattr(
        "sase.finalizers.controller_context.ensure_final_declaration_or_recover",
        lambda **_kwargs: (
            recovery_calls.append(True) or InvokeResult(content="recovered")
        ),
    )

    result = _ensure(tmp_path)

    assert result.content == "recovered"
    assert recovery_calls == [True]
    assert not (tmp_path / FINAL_SUBMISSION_FILENAME).exists()


def test_malformed_reservation_refuses_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    _sealed, prepared, _observations, _repo_id = _seal_prepared(monkeypatch, tmp_path)
    _stage_monitor(
        monkeypatch,
        tmp_path,
        prepared_intent_ref=prepared.intent_ref,
        reservation={**_reservation(), "command": [""]},
    )

    publication = publish_final_context()

    assert publication.submission_required is True
    assert _coverage_reason(publication) == "unreadable_prepared_reservation"


def test_observation_drift_refuses_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    _sealed, prepared, observations, _repo_id = _seal_prepared(monkeypatch, tmp_path)
    _stage_monitor(
        monkeypatch,
        tmp_path,
        prepared_intent_ref=prepared.intent_ref,
        reservation=_reservation(),
    )
    drifted = [{**observations[0], "head_tree": _digest("drifted-tree")}]
    monkeypatch.setattr(
        "sase.finalizers.prepare.observe_completion_repositories",
        lambda _root: drifted,
    )

    publication = publish_final_context()

    assert publication.submission_required is True
    assert _coverage_reason(publication) == "stale_observations"


def test_owner_drift_refuses_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    _sealed, prepared, _observations, _repo_id = _seal_prepared(monkeypatch, tmp_path)
    _stage_monitor(
        monkeypatch,
        tmp_path,
        prepared_intent_ref=prepared.intent_ref,
        reservation=_reservation(),
    )
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-drifted")

    publication = publish_final_context()

    assert publication.submission_required is True
    assert _coverage_reason(publication) == "prepared_creator_run_mismatch"


def test_command_drift_refuses_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    _sealed, prepared, _observations, _repo_id = _seal_prepared(monkeypatch, tmp_path)
    drifted = {**_reservation(), "command": ["just", "check-full"]}
    _stage_monitor(
        monkeypatch,
        tmp_path,
        prepared_intent_ref=prepared.intent_ref,
        reservation=drifted,
    )

    publication = publish_final_context()

    assert publication.submission_required is True
    assert _coverage_reason(publication) == "prepared_command_mismatch"


def test_plan_digest_drift_refuses_adapter_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    sealed, prepared, _observations, repo_id = _seal_prepared(monkeypatch, tmp_path)
    _stage_monitor(
        monkeypatch,
        tmp_path,
        prepared_intent_ref=prepared.intent_ref,
        reservation=_reservation(),
    )

    decision = evaluate_prepared_starter_coverage_for_artifacts(
        tmp_path,
        plan_digest="b" * 64,
        obligation_ids=[repo_id],
        run_id=sealed.context.run_id,
        agent_id=sealed.context.agent_id,
    )

    assert decision.eligible is False
    assert "changed_finalizer_requirements" in decision.reasons


def test_uncovered_new_work_still_requires_submission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extra = tmp_path / "linked"
    extra.mkdir()
    holder: dict[str, DirtyState] = {}

    def collect(_root: object) -> DirtyState:
        return holder["state"]

    holder["state"] = DirtyState(
        project_dir=str(tmp_path),
        repos=(
            DirtyRepo(
                name="main",
                path=str(tmp_path),
                changed_files=("src/app.py",),
                kind="main",
            ),
        ),
        details="dirty",
    )
    prepare_dirty_declaration(monkeypatch, tmp_path, collect=collect)
    _sealed, prepared, _observations, repo_id = _seal_prepared(monkeypatch, tmp_path)
    _stage_monitor(
        monkeypatch,
        tmp_path,
        prepared_intent_ref=prepared.intent_ref,
        reservation=_reservation(),
    )
    holder["state"] = DirtyState(
        project_dir=str(tmp_path),
        repos=(
            holder["state"].repos[0],
            DirtyRepo(
                name="plans",
                path=str(extra),
                changed_files=("note.md",),
                kind="sibling",
            ),
        ),
        details="dirty",
    )

    publication = publish_final_context()

    assert publication.submission_required is True
    coverage = publication.payload["commit_declaration"]["prepared_coverage"]
    assert coverage["eligible"] is False
    assert repo_id in coverage["covered_repository_ids"]
    assert str(coverage["reason"]).startswith("uncovered_repository:")
    extra_ids = [
        item.obligation_id
        for item in publication.context.obligations
        if item.obligation_id != repo_id
    ]
    assert extra_ids
    assert extra_ids[0] not in coverage["covered_repository_ids"]


def test_reserved_starter_green_execution_skips_commit_hooks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {"repos": (dirty_repo(repo),)}
    patch_controller_dirty(monkeypatch, repo, dirty)
    from sase.finalizers.plan import resolve_and_persist_finalizer_plan
    from sase.macro.directives import PromptDirectives

    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    _sealed, prepared, _observations, repo_id = _seal_prepared(monkeypatch, artifacts)
    _stage_monitor(
        monkeypatch,
        artifacts,
        prepared_intent_ref=prepared.intent_ref,
        reservation=_reservation(),
    )
    stitch = MagicMock(return_value=StitchCommandResult(returncode=0, stdout="ok\n"))
    pin = MagicMock(return_value=("pin", None))
    monkeypatch.setattr("sase.finalizers.commit_execution.run_stitch_create", stitch)
    monkeypatch.setattr(
        "sase.finalizers.commit_dispatch._maybe_write_revision_pin", pin
    )

    result = run_controller(artifacts)

    assert result.content == "done"
    payload = json.loads((artifacts / "finalizer_result.json").read_text())
    assert payload["status"] == "success"
    evidence = payload["instances"][0]["evidence"]
    kinds = [item["kind"] for item in evidence]
    assert PREPARED_EVIDENCE_KIND in kinds
    assert CARRY_EVIDENCE_KIND not in kinds
    parsed = json.loads(
        next(
            item["value"] for item in evidence if item["kind"] == PREPARED_EVIDENCE_KIND
        )
    )
    assert parsed["repo_id"] == repo_id
    assert parsed["staged_ref"] == _STAGED_ID
    stitch.assert_not_called()
    pin.assert_not_called()
    assert not (artifacts / FINAL_SUBMISSION_FILENAME).exists()
    assert not (artifacts / "commit_results.json").exists()
    assert dirty["repos"] == (dirty_repo(repo),)


def test_ineligible_red_execution_does_not_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {"repos": (dirty_repo(repo),)}
    patch_controller_dirty(monkeypatch, repo, dirty)
    from sase.finalizers.plan import resolve_and_persist_finalizer_plan
    from sase.macro.directives import PromptDirectives

    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    _sealed, prepared, _observations, _repo_id = _seal_prepared(monkeypatch, artifacts)
    _stage_monitor(
        monkeypatch,
        artifacts,
        prepared_intent_ref=prepared.intent_ref,
    )
    stitch = MagicMock(return_value=StitchCommandResult(returncode=0, stdout="ok\n"))
    monkeypatch.setattr("sase.finalizers.commit_execution.run_stitch_create", stitch)
    monkeypatch.setattr(
        "sase.finalizers.controller_context.ensure_final_declaration_or_recover",
        lambda **_kwargs: InvokeResult(content="recovered"),
    )

    with pytest.raises(BuiltinCommitFinalizerError, match="accepted declaration"):
        run_controller(artifacts)

    stitch.assert_not_called()
    assert not (artifacts / FINAL_SUBMISSION_FILENAME).exists()
    assert dirty["repos"] == (dirty_repo(repo),)


def test_host_completion_installs_sealed_declaration_after_starter_satisfaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    _sealed, prepared, _observations, repo_id = _seal_prepared(monkeypatch, tmp_path)
    _stage_monitor(
        monkeypatch,
        tmp_path,
        prepared_intent_ref=prepared.intent_ref,
        reservation=_reservation(),
    )
    publication = publish_final_context()
    assert publication.submission_required is False

    install_prepared_declaration(prepared.intent, str(tmp_path), publication)

    receipt = json.loads(
        (tmp_path / HOST_COMPLETION_RECEIPT_FILENAME).read_text(encoding="utf-8")
    )
    assert receipt["status"] == "finalizing"
    assert receipt["reason"] == "prepared_declaration_install"
    accepted = json.loads(
        (tmp_path / FINAL_SUBMISSION_FILENAME).read_text(encoding="utf-8")
    )
    decision = accepted["submission"]["payloads"][0]["payload"]["repositories"][0]
    assert decision["repo_id"] == repo_id
    assert decision["action"] == "commit"
    assert "synthesized" not in accepted
    refreshed = publish_final_context()
    assert refreshed.submission_required is True
