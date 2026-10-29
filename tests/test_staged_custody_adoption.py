"""Custody adoption: carry/prepared settlement, custody records, and seam."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sase.axe.run_agent_exec_staged import (
    CARRIED_CUSTODY_META_KEY,
    STAGED_HANDOFF_ADOPTERS,
    _StagedAdoptionOutcome,
    StagedInlineContinuation,
    _finalizer_settlement_refusal,
    dispatch_completed_staged_handoff,
)
from sase.agent.staged_handoff import (
    read_adoption_receipt,
    write_staged_handoff,
    write_staged_handoff_response,
)
from tests._axe_run_agent_exec_helpers import make_exec_ctx

RUN_ID = "20261028120000"
STAGED_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
DIGEST_MAIN = "digest-main-1"
DIGEST_LINKED = "digest-linked-1"


def _staged_record(
    *,
    kind: str = "questions",
    successor_workspace: str = "inherit",
    carry_allowed: bool = True,
    staged_id: str = STAGED_ID,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "staged_id": staged_id,
        "kind": kind,
        "created_at": "2026-10-28T12:00:00Z",
        "payload": {"note": "test"},
        "successor_workspace": successor_workspace,
        "carry_allowed": carry_allowed,
        "dirty_obligations_at_stage": [],
    }


def _meta(artifacts: Path) -> dict[str, Any]:
    return {
        "name": "agent",
        "workspace_dir": str(artifacts.parent),
        "finalizer_status": {
            "phase": "settled",
            "status": "success",
            "run_id": "controller-run-1",
            "plan_digest": "digest-1",
            "started_at": datetime(2026, 10, 28, 12, 1, tzinfo=UTC).timestamp(),
        },
    }


def _write_meta(artifacts: Path, meta: dict[str, Any]) -> None:
    (artifacts / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")


def _write_result(
    artifacts: Path,
    *,
    evidence: list[dict[str, Any]] | None = None,
    status: str = "success",
) -> None:
    instances = [
        {
            "instance_id": "commit",
            "status": "success" if status == "success" else status,
            "evidence": evidence or [],
        }
    ]
    (artifacts / "finalizer_result.json").write_text(
        json.dumps({"status": status, "instances": instances}), encoding="utf-8"
    )


def _write_context_json(artifacts: Path) -> None:
    (artifacts / "final_context.json").write_text(
        json.dumps(
            {
                "context": {
                    "run_id": RUN_ID,
                    "agent_id": "agent",
                    "plan_digest": "digest-1",
                }
            }
        ),
        encoding="utf-8",
    )


def _carry_evidence(
    repo_id: str, digest: str, staged_ref: str = STAGED_ID
) -> dict[str, Any]:
    return {
        "kind": "carried_repo",
        "value": json.dumps(
            {"digest": digest, "repo_id": repo_id, "staged_ref": staged_ref},
            separators=(",", ":"),
            sort_keys=True,
        ),
    }


def _prepared_evidence(
    repo_id: str, digest: str, staged_ref: str = STAGED_ID
) -> dict[str, Any]:
    item = _carry_evidence(repo_id, digest, staged_ref)
    return {"kind": "prepared_repo", "value": item["value"]}


def _context(
    *,
    staged_ref: str = STAGED_ID,
    kind: str = "questions",
    successor_workspace: str = "inherit",
    carry_allowed: bool = True,
    prepared_intent_ref: str | None = None,
    obligations: list[tuple[str, str]] | None = None,
) -> SimpleNamespace:
    from sase.core.finalizer_wire import FinalizerHandoffWire

    obs = obligations if obligations is not None else [("repo-1", DIGEST_MAIN)]
    return SimpleNamespace(
        obligations=[
            SimpleNamespace(kind="repository", obligation_id=repo_id, digest=digest)
            for repo_id, digest in obs
        ],
        handoff=FinalizerHandoffWire(
            kind=kind,
            staged_ref=staged_ref,
            successor_workspace=successor_workspace,
            carry_allowed=carry_allowed,
            prepared_intent_ref=prepared_intent_ref,
        ),
    )


def _plan() -> SimpleNamespace:
    return SimpleNamespace(
        plan_digest="digest-1",
        entries=(SimpleNamespace(instance_id="commit", provider_ref="builtin@commit"),),
    )


def _patch_common(
    monkeypatch,
    *,
    context: SimpleNamespace,
    dirty_ids: list[str],
    submission: dict[str, Any] | None = None,
    submission_current: bool = True,
) -> None:
    monkeypatch.setattr(
        "sase.finalizers.plan.authenticate_resolved_finalizer_plan",
        lambda _root: _plan(),
    )
    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_state.collect_dirty_state",
        lambda _project_dir, artifact_root=None: SimpleNamespace(
            repos=[object() for _ in dirty_ids]
        ),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration_store.repository_obligation_id",
        lambda _repo, _ids=list(dirty_ids): _ids.pop(0) if _ids else "repo-unknown",
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration.load_latest_finalizer_context",
        lambda _root: context,
    )
    if submission is not None:
        monkeypatch.setattr(
            "sase.finalizers.declaration.load_latest_finalizer_submission",
            lambda _root: submission,
        )
    monkeypatch.setattr(
        "sase.finalizers.declaration.final_submission_is_current",
        lambda **_kwargs: submission_current,
    )


def _artifacts(tmp_path: Path) -> Path:
    artifacts = tmp_path / RUN_ID
    artifacts.mkdir(exist_ok=True)
    return artifacts


def test_all_carry_settles_with_current_declaration(
    tmp_path: Path, monkeypatch
) -> None:
    artifacts = _artifacts(tmp_path)
    record = _staged_record()
    _write_meta(artifacts, _meta(artifacts))
    _write_context_json(artifacts)
    _write_result(artifacts, evidence=[_carry_evidence("repo-1", DIGEST_MAIN)])
    (artifacts / "final_submission.json").write_text("{}", encoding="utf-8")
    ctx = _context()
    _patch_common(
        monkeypatch,
        context=ctx,
        dirty_ids=["repo-1"],
        submission={"accepted_deferrals": []},
    )
    assert (
        _finalizer_settlement_refusal(
            record,
            artifacts_dir=str(artifacts),
            run_metadata=json.loads((artifacts / "agent_meta.json").read_text()),
        )
        is None
    )


def test_mixed_carry_and_deferral_settles(tmp_path: Path, monkeypatch) -> None:
    artifacts = _artifacts(tmp_path)
    record = _staged_record()
    _write_meta(artifacts, _meta(artifacts))
    _write_context_json(artifacts)
    _write_result(
        artifacts,
        evidence=[_carry_evidence("repo-1", DIGEST_MAIN)],
    )
    (artifacts / "final_submission.json").write_text("{}", encoding="utf-8")
    ctx = _context(obligations=[("repo-1", DIGEST_MAIN), ("repo-2", DIGEST_LINKED)])
    # Two dirty repos: repo-1 carried, repo-2 deferred.
    _patch_common(
        monkeypatch,
        context=ctx,
        dirty_ids=["repo-1", "repo-2"],
        submission={
            "accepted_deferrals": [{"instance_id": "commit", "repo_id": "repo-2"}]
        },
    )
    assert (
        _finalizer_settlement_refusal(
            record,
            artifacts_dir=str(artifacts),
            run_metadata=json.loads((artifacts / "agent_meta.json").read_text()),
        )
        is None
    )


def test_prepared_starter_without_submission_settles(
    tmp_path: Path, monkeypatch
) -> None:
    artifacts = _artifacts(tmp_path)
    record = _staged_record(kind="monitor", carry_allowed=False)
    _write_meta(artifacts, _meta(artifacts))
    _write_context_json(artifacts)
    _write_result(artifacts, evidence=[_prepared_evidence("repo-1", DIGEST_MAIN)])
    # No final_submission.json: prepared omission path.
    ctx = _context(
        kind="monitor",
        successor_workspace="inherit",
        carry_allowed=False,
        prepared_intent_ref="intent-1",
    )
    _patch_common(monkeypatch, context=ctx, dirty_ids=["repo-1"], submission=None)
    # load_latest_finalizer_submission must not be called; ensure it would fail.
    monkeypatch.setattr(
        "sase.finalizers.declaration.load_latest_finalizer_submission",
        lambda _root: (_ for _ in ()).throw(AssertionError("no submission expected")),
    )
    assert (
        _finalizer_settlement_refusal(
            record,
            artifacts_dir=str(artifacts),
            run_metadata=json.loads((artifacts / "agent_meta.json").read_text()),
        )
        is None
    )


def test_mismatched_staged_ref_does_not_authorize_carry(
    tmp_path: Path, monkeypatch
) -> None:
    artifacts = _artifacts(tmp_path)
    record = _staged_record()
    _write_meta(artifacts, _meta(artifacts))
    _write_context_json(artifacts)
    _write_result(
        artifacts,
        evidence=[_carry_evidence("repo-1", DIGEST_MAIN, staged_ref="other-stage")],
    )
    (artifacts / "final_submission.json").write_text("{}", encoding="utf-8")
    ctx = _context()
    _patch_common(
        monkeypatch,
        context=ctx,
        dirty_ids=["repo-1"],
        submission={"accepted_deferrals": []},
    )
    reason = _finalizer_settlement_refusal(
        record,
        artifacts_dir=str(artifacts),
        run_metadata=json.loads((artifacts / "agent_meta.json").read_text()),
    )
    assert reason is not None


def test_malformed_evidence_does_not_authorize_carry(
    tmp_path: Path, monkeypatch
) -> None:
    artifacts = _artifacts(tmp_path)
    record = _staged_record()
    _write_meta(artifacts, _meta(artifacts))
    _write_context_json(artifacts)
    _write_result(artifacts, evidence=[{"kind": "carried_repo", "value": "not-json"}])
    (artifacts / "final_submission.json").write_text("{}", encoding="utf-8")
    ctx = _context()
    _patch_common(
        monkeypatch,
        context=ctx,
        dirty_ids=["repo-1"],
        submission={"accepted_deferrals": []},
    )
    assert (
        _finalizer_settlement_refusal(
            record,
            artifacts_dir=str(artifacts),
            run_metadata=json.loads((artifacts / "agent_meta.json").read_text()),
        )
        is not None
    )


def test_dirt_added_after_settlement_holds(tmp_path: Path, monkeypatch) -> None:
    artifacts = _artifacts(tmp_path)
    record = _staged_record()
    _write_meta(artifacts, _meta(artifacts))
    _write_context_json(artifacts)
    # Evidence covers repo-1 only; live dirt now includes repo-2.
    _write_result(artifacts, evidence=[_carry_evidence("repo-1", DIGEST_MAIN)])
    (artifacts / "final_submission.json").write_text("{}", encoding="utf-8")
    ctx = _context(obligations=[("repo-1", DIGEST_MAIN), ("repo-2", DIGEST_LINKED)])
    _patch_common(
        monkeypatch,
        context=ctx,
        dirty_ids=["repo-1", "repo-2"],
        submission={"accepted_deferrals": []},
    )
    assert (
        _finalizer_settlement_refusal(
            record,
            artifacts_dir=str(artifacts),
            run_metadata=json.loads((artifacts / "agent_meta.json").read_text()),
        )
        is not None
    )


def _continuation(tmp_path: Path, artifacts: Path):
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    from dataclasses import replace

    ctx = replace(ctx, artifacts_dir=str(artifacts), agent_name="agent")
    from sase.axe.run_agent_exec import LoopState

    state = LoopState(
        current_prompt="p",
        current_role_suffix="",
        current_artifacts_dir=str(artifacts),
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="p",
    )
    return StagedInlineContinuation(ctx=ctx, state=state)


def _settled_carry_artifacts(
    tmp_path: Path, monkeypatch, *, kind: str = "questions"
) -> tuple[Path, dict[str, Any]]:
    artifacts = _artifacts(tmp_path)
    record = _staged_record(kind=kind)
    write_staged_handoff(record, artifacts_dir=str(artifacts))
    write_staged_handoff_response(
        str(record["staged_id"]), "provider response", artifacts_dir=str(artifacts)
    )
    _write_meta(artifacts, _meta(artifacts))
    _write_context_json(artifacts)
    _write_result(artifacts, evidence=[_carry_evidence("repo-1", DIGEST_MAIN)])
    (artifacts / "final_submission.json").write_text("{}", encoding="utf-8")
    ctx = _context(kind=kind)
    _patch_common(
        monkeypatch,
        context=ctx,
        dirty_ids=["repo-1"],
        submission={"accepted_deferrals": []},
    )
    # load_latest_finalizer_context is used twice (refusal + custody persist);
    # the dirty-id pop mock above would exhaust, so re-patch id mapping stably.
    monkeypatch.setattr(
        "sase.finalizers.declaration_store.repository_obligation_id",
        lambda _repo: "repo-1",
    )
    return artifacts, record


def test_controlled_adopter_proves_generic_seam_and_records_custody(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    artifacts, record = _settled_carry_artifacts(tmp_path, monkeypatch)
    continuation = _continuation(tmp_path, artifacts)
    seen: list[str] = []

    def controlled(staged, _meta, cont, response):
        seen.append(response)
        assert staged["staged_id"] == record["staged_id"]
        return _StagedAdoptionOutcome(
            outcome="test-done", custodian=str(artifacts / "successor")
        )

    monkeypatch.setitem(STAGED_HANDOFF_ADOPTERS, "questions", controlled)
    result = dispatch_completed_staged_handoff(str(artifacts), continuation)
    assert result is not None and result.adopted and result.outcome == "test-done"
    assert seen == ["provider response"]
    meta = json.loads((artifacts / "agent_meta.json").read_text(encoding="utf-8"))
    custody = meta.get(CARRIED_CUSTODY_META_KEY)
    assert isinstance(custody, list) and len(custody) == 1
    entry = custody[0]
    assert entry["repo_id"] == "repo-1"
    assert entry["digest"] == DIGEST_MAIN
    assert entry["staged_id"] == record["staged_id"]
    assert entry["origin_run"] == "controller-run-1"
    assert entry["carried_to"] == str(artifacts / "successor")
    receipt = read_adoption_receipt(str(artifacts))
    assert receipt is not None and receipt["outcome"] == "adopted"


def test_failed_adoption_leaves_origin_custody_intact(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    artifacts, record = _settled_carry_artifacts(
        tmp_path, monkeypatch, kind="questions"
    )
    continuation = _continuation(tmp_path, artifacts)

    def failing(_staged, _meta, _cont, _response):
        return "plan_rejected"

    monkeypatch.setitem(STAGED_HANDOFF_ADOPTERS, "questions", failing)
    result = dispatch_completed_staged_handoff(str(artifacts), continuation)
    assert result is not None and not result.adopted
    meta = json.loads((artifacts / "agent_meta.json").read_text(encoding="utf-8"))
    custody = meta.get(CARRIED_CUSTODY_META_KEY)
    assert isinstance(custody, list) and len(custody) == 1
    assert custody[0]["carried_to"] is None
    receipt = read_adoption_receipt(str(artifacts))
    assert receipt is not None and receipt["outcome"] == "handoff_not_adopted"


def test_successor_inherits_carried_primary_and_linked_dirt(
    tmp_path: Path, monkeypatch
) -> None:
    """Same-workspace successor sees carried linked dirt as its own obligation."""

    from sase._linked_repo_markers import (
        opened_repo_records,
        record_opened_external_repo,
        record_opened_linked_repo,
    )
    from sase.llm_provider.commit_finalizer_baseline import FINALIZER_BASELINE_FILENAME
    from sase.llm_provider.commit_finalizer_inheritance import (
        inherit_commit_finalizer_responsibility,
    )
    from sase.llm_provider.commit_finalizer_state import collect_dirty_state
    from tests.finalizers_live_e2e_test_helpers import init_live_repo

    workspace = init_live_repo(tmp_path / "workspace")
    linked = init_live_repo(workspace / "sase" / "repos" / "linked" / "core")
    external = init_live_repo(
        workspace / "sase" / "repos" / "external" / "projects" / "widget"
    )

    parent = tmp_path / "parent-artifacts"
    parent.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(parent))
    record_opened_linked_repo(
        "core",
        str(linked),
        reason="inspect the linked core",
        opened_at="2026-10-27T09:00:00+00:00",
    )
    record_opened_external_repo(
        "widget",
        str(external),
        reason="inspect the widget source",
        opened_at="2026-10-27T11:00:00+00:00",
    )
    (linked / "linked-work.txt").write_text("linked dirt\n", encoding="utf-8")
    (external / "external-work.txt").write_text("external dirt\n", encoding="utf-8")
    parent_dirty = collect_dirty_state(str(workspace), artifact_root=parent)
    parent_names = {(repo.kind, repo.name) for repo in parent_dirty.repos}
    assert ("sibling", "core") in parent_names
    assert ("external", "widget") in parent_names

    audit_log = tmp_path / "repo_opens.jsonl"
    monkeypatch.setattr(
        "sase.repo_open_log._repo_open_log_path", lambda _project: audit_log
    )
    child = tmp_path / "child-artifacts"
    assert inherit_commit_finalizer_responsibility(
        parent_artifacts_dir=str(parent),
        child_artifacts_dir=str(child),
        predecessor_name="agent-0",
        successor_name="agent-1",
        project_name="sase-test-project",
        parent_workspace_dir=str(workspace),
        child_workspace_dir=str(workspace),
        workspace_num=3,
    )
    assert (child / FINALIZER_BASELINE_FILENAME).is_file()
    assert opened_repo_records(child)

    child_dirty = collect_dirty_state(str(workspace), artifact_root=child)
    child_names = {(repo.kind, repo.name) for repo in child_dirty.repos}
    assert ("sibling", "core") in child_names
    assert ("external", "widget") in child_names
    # Successor can commit: both carried paths are still reported as dirty with
    # the same checkout paths the origin observed.
    child_paths = {repo.path for repo in child_dirty.repos}
    assert any("core" in path for path in child_paths)
    assert any("widget" in path for path in child_paths)
