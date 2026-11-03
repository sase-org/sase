"""Prepared starter coverage and identity validation tests."""

import json
from pathlib import Path
from typing import Any

import pytest
import sase.finalizers.prepared_coverage as prepared_coverage

from sase.finalizers.declaration import FINAL_SUBMISSION_FILENAME, publish_final_context
from sase.finalizers.controller_context import ensure_current_declaration
from sase.finalizers.declaration_format import format_context_pretty
from sase.finalizers.declaration_store import FinalizerDeclarationError
from sase.finalizers.prepare import bind_prepared_completion
from sase.finalizers.prepared_coverage import (
    PREPARED_RESERVATION_PAYLOAD_KEY,
    PreparedStarterCoverage,
    evaluate_prepared_starter_coverage_for_artifacts,
    prepared_coverage_omits_starter_submission,
)
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState
from sase.llm_provider.types import InvokeResult
from sase.monitor.delivery import HOST_COMPLETION_RECEIPT_FILENAME

from ._finalizers_prepared_bridge_helpers import (
    COMMAND,
    FINGERPRINT,
    MONITOR_ID,
    STAGED_ID,
    digest,
    prepare_dirty_declaration,
    reservation,
    run_silent_check_catalog,
    seal_prepared,
    stage_monitor,
)


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
    parsed = prepared_coverage._reservation_from_staged_payload(
        {PREPARED_RESERVATION_PAYLOAD_KEY: reservation()}
    )
    assert parsed is not None
    assert parsed["staged_id"] == STAGED_ID
    assert parsed["command"] == COMMAND
    assert prepared_coverage._reservation_from_staged_payload({}) is None
    with pytest.raises(FinalizerDeclarationError) as exc_info:
        prepared_coverage._reservation_from_staged_payload(
            {PREPARED_RESERVATION_PAYLOAD_KEY: "nope"}
        )
    assert exc_info.value.code == "unreadable_prepared_reservation"
    with pytest.raises(FinalizerDeclarationError) as exc_info:
        prepared_coverage._reservation_from_staged_payload(
            {PREPARED_RESERVATION_PAYLOAD_KEY: {**reservation(), "command": []}}
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
    assert prepared_coverage._host_completion_is_installing(tmp_path) is True
    assert prepared_coverage_omits_starter_submission(tmp_path, coverage) is False


def test_reserved_starter_omits_submission_after_handoff_only_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    sealed_publication, prepared, _observations, repo_id = seal_prepared(
        monkeypatch, tmp_path
    )
    sealed_digest = sealed_publication.context.context_digest
    stage_monitor(
        monkeypatch,
        tmp_path,
        prepared_intent_ref=prepared.intent_ref,
        reservation=reservation(),
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
    _sealed, prepared, _observations, repo_id = seal_prepared(monkeypatch, tmp_path)
    bound = bind_prepared_completion(
        prepared.intent_ref,
        monitor_id=MONITOR_ID,
        command=COMMAND,
        request_fingerprint=FINGERPRINT,
        artifacts_dir=tmp_path,
    )
    assert bound["status"] == "bound"
    stage_monitor(
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
    _sealed, prepared, _observations, _repo_id = seal_prepared(monkeypatch, tmp_path)
    stage_monitor(
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
    _sealed, prepared, _observations, _repo_id = seal_prepared(monkeypatch, tmp_path)
    stage_monitor(
        monkeypatch,
        tmp_path,
        prepared_intent_ref=prepared.intent_ref,
        reservation={**reservation(), "command": [""]},
    )

    publication = publish_final_context()

    assert publication.submission_required is True
    assert _coverage_reason(publication) == "unreadable_prepared_reservation"


def test_observation_drift_refuses_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    _sealed, prepared, observations, _repo_id = seal_prepared(monkeypatch, tmp_path)
    stage_monitor(
        monkeypatch,
        tmp_path,
        prepared_intent_ref=prepared.intent_ref,
        reservation=reservation(),
    )
    drifted = [{**observations[0], "head_tree": digest("drifted-tree")}]
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
    _sealed, prepared, _observations, _repo_id = seal_prepared(monkeypatch, tmp_path)
    stage_monitor(
        monkeypatch,
        tmp_path,
        prepared_intent_ref=prepared.intent_ref,
        reservation=reservation(),
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
    _sealed, prepared, _observations, _repo_id = seal_prepared(monkeypatch, tmp_path)
    drifted = {**reservation(), "command": ["just", "check-full"]}
    stage_monitor(
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
    sealed, prepared, _observations, repo_id = seal_prepared(monkeypatch, tmp_path)
    stage_monitor(
        monkeypatch,
        tmp_path,
        prepared_intent_ref=prepared.intent_ref,
        reservation=reservation(),
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


def test_non_root_rename_does_not_reuse_prepared_creator_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"name": "agent-1"}), encoding="utf-8"
    )
    sealed, prepared, _observations, repo_id = seal_prepared(monkeypatch, tmp_path)
    stage_monitor(
        monkeypatch,
        tmp_path,
        prepared_intent_ref=prepared.intent_ref,
        reservation=reservation(),
    )
    from sase.agent._agent_session_promotion import promote_agent_to_agent_session

    promote_agent_to_agent_session(tmp_path, "agent-1")
    metadata_path = tmp_path / "agent_meta.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["name"] = "agent-1--1"
    metadata["role_suffix"] = "--1"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    decision = evaluate_prepared_starter_coverage_for_artifacts(
        tmp_path,
        plan_digest=sealed.context.plan_digest,
        obligation_ids=[repo_id],
        run_id=sealed.context.run_id,
        agent_id="agent-1--1",
    )

    assert decision.eligible is False
    assert decision.reason == "prepared_creator_agent_mismatch"


def test_different_run_does_not_reuse_prepared_creator_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare_dirty_declaration(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"name": "agent-1"}), encoding="utf-8"
    )
    sealed, prepared, _observations, repo_id = seal_prepared(monkeypatch, tmp_path)
    stage_monitor(
        monkeypatch,
        tmp_path,
        prepared_intent_ref=prepared.intent_ref,
        reservation=reservation(),
    )
    from sase.agent._agent_session_promotion import promote_agent_to_agent_session

    promote_agent_to_agent_session(tmp_path, "agent-1")

    decision = evaluate_prepared_starter_coverage_for_artifacts(
        tmp_path,
        plan_digest=sealed.context.plan_digest,
        obligation_ids=[repo_id],
        run_id="different-run",
        agent_id="agent-1--0",
    )

    assert decision.eligible is False
    assert decision.reason == "prepared_creator_run_mismatch"


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
    _sealed, prepared, _observations, repo_id = seal_prepared(monkeypatch, tmp_path)
    stage_monitor(
        monkeypatch,
        tmp_path,
        prepared_intent_ref=prepared.intent_ref,
        reservation=reservation(),
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
