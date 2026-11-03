"""Prepared starter commit and host completion lifecycle tests."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.finalizers.commit import BuiltinCommitFinalizerError, StitchCommandResult
from sase.finalizers.commit_carry import CARRY_EVIDENCE_KIND, PREPARED_EVIDENCE_KIND
from sase.finalizers.declaration import (
    FINAL_SUBMISSION_FILENAME,
    SASE_FINAL_TURN_NONCE_ENV,
    publish_final_context,
)
from sase.finalizers.prepare import bind_prepared_completion
from sase.finalizers._prepare_reservations import reserve_prepared_intent
from sase.llm_provider.types import InvokeResult
from sase.macro.directives import PromptDirectives
from sase.monitor.delivery import HOST_COMPLETION_RECEIPT_FILENAME
from sase.monitor.diagnostics import diagnostic_manifest_path
from sase.monitor.host_completion import (
    HOST_COMPLETION_IDENTITY,
    settle_host_completion,
)
from sase.monitor.host_completion_state import install_prepared_declaration
from sase.monitor.output import OutputCapture
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.finalizers.plan import resolve_and_persist_finalizer_plan

from .finalizer_declaration_channel_test_helpers import valid_manifest
from .finalizers_protocol_harness_test_helpers import (
    dirty_repo,
    patch_dirty as patch_controller_dirty,
    prepare_agent_env,
    run_controller,
    successful_stitch,
)
from ._finalizers_prepared_bridge_helpers import (
    COMMAND,
    FINGERPRINT,
    MONITOR_ID,
    STAGED_ID,
    prepare_dirty_declaration,
    reservation,
    run_silent_check_catalog,
    seal_prepared,
    stage_monitor,
)


def test_promoted_prepared_starter_and_nonce_free_host_completion_commit_on_green(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    prepare_agent_env(monkeypatch, artifacts, repo)
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setenv("SASE_WORKSPACE_NUM", "20")
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"name": "agent-1"}), encoding="utf-8"
    )
    dirty = {"repos": (dirty_repo(repo),)}
    patch_controller_dirty(monkeypatch, repo, dirty)
    from sase.agent._agent_session_promotion import promote_agent_to_agent_session

    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    _sealed, prepared, observations, repo_id = seal_prepared(
        monkeypatch, artifacts, command=["just", "check-full"]
    )
    reservation = {
        "staged_id": STAGED_ID,
        "monitor_id": MONITOR_ID,
        "request_fingerprint": FINGERPRINT,
        "command": ["just", "check-full"],
    }
    reserve_prepared_intent(prepared.intent_ref, reservation, artifacts_dir=artifacts)
    stage_monitor(
        monkeypatch,
        artifacts,
        prepared_intent_ref=prepared.intent_ref,
        reservation=reservation,
    )
    assert promote_agent_to_agent_session(artifacts, "agent-1") == "agent-1--0"
    promoted_publication = publish_final_context(artifacts_dir=str(artifacts))
    assert promoted_publication.submission_required is False
    assert promoted_publication.payload["commit_declaration"]["prepared_coverage"][
        "covered_repository_ids"
    ] == [repo_id]

    host_stitches: list[str] = []
    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_create",
        successful_stitch(artifacts, dirty, host_stitches),
    )
    monkeypatch.setattr(
        "sase.finalizers.commit_dispatch._maybe_write_revision_pin",
        lambda *_args, **_kwargs: ("pin", None),
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
    assert parsed["staged_ref"] == STAGED_ID
    assert host_stitches == []
    assert not (artifacts / FINAL_SUBMISSION_FILENAME).exists()
    assert not (artifacts / "commit_results.json").exists()
    assert dirty["repos"] == (dirty_repo(repo),)

    bound = bind_prepared_completion(
        prepared.intent_ref,
        monitor_id=MONITOR_ID,
        command=["just", "check-full"],
        request_fingerprint=FINGERPRINT,
        staged_id=STAGED_ID,
        artifacts_dir=artifacts,
    )
    assert bound["status"] == "bound"
    stages = [
        {
            "stage_id": stage_id,
            "name": name,
            "status": "passed",
            "exit_code": 0,
            "diagnostic_refs": [],
            "counts": {},
            "retained_ranges": [],
            "capture_errors": [],
        }
        for stage_id, name in (
            ("formatting", "fmt (python)"),
            ("ruff", "lint (ruff)"),
            ("mypy", "lint (mypy)"),
            ("validation", "SASE validation"),
            ("full_tests", "test (full)"),
        )
    ]
    manifest_path = diagnostic_manifest_path(artifacts)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {"schema_version": CONTINUATION_WIRE_SCHEMA_VERSION, "stages": stages}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sase.monitor.host_completion_state.observe_completion_repositories",
        lambda _root: observations,
    )
    monkeypatch.delenv(SASE_FINAL_TURN_NONCE_ENV, raising=False)
    monkeypatch.setattr(
        "sase.monitor.host_completion_execute._NoModelProvider.invoke",
        lambda *_args, **_kwargs: pytest.fail(
            "host completion must not invoke a model"
        ),
    )
    host_meta = {
        "monitor_id": MONITOR_ID,
        "monitor_completion_ref": prepared.intent_ref,
        "monitor_profile": "verify",
        "monitor_command": "just check-full",
        "monitor_execution_argv": ["just", "check-full"],
        "workspace_dir": "/ws/20",
        "workspace_num": 20,
        "continuation_workspace_ref": "/ws/20",
        "continuation_monitor_result_id": "result-1",
        "monitor_next_action": "Diagnose failures or stale verification, then finish.",
        "name": "agent-1--0",
    }
    host_result = settle_host_completion(
        str(artifacts),
        host_meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=182,
        project_name="proj",
        launch_recovery=lambda *_args, **_kwargs: pytest.fail(
            "green prepared completion must not launch recovery"
        ),
        release_claim=lambda *_args, **_kwargs: None,
        capture=OutputCapture(),
        selected_action="complete",
    )
    assert host_result is not None
    assert host_result.launch_result is not None
    assert host_result.launch_result.host_completed is True
    assert host_result.launch_result.agent_name == HOST_COMPLETION_IDENTITY
    assert os.environ.get(SASE_FINAL_TURN_NONCE_ENV)
    assert host_stitches == ["main"]
    assert dirty["repos"] == ()
    host_receipt = json.loads(
        (artifacts / HOST_COMPLETION_RECEIPT_FILENAME).read_text(encoding="utf-8")
    )
    assert host_receipt["status"] == "completed"
    assert host_receipt["commit_receipts"]


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
    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    _sealed, prepared, _observations, _repo_id = seal_prepared(monkeypatch, artifacts)
    stage_monitor(
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
    _sealed, prepared, _observations, repo_id = seal_prepared(monkeypatch, tmp_path)
    stage_monitor(
        monkeypatch,
        tmp_path,
        prepared_intent_ref=prepared.intent_ref,
        reservation=reservation(),
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
