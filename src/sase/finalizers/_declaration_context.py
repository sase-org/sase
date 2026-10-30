"""Live context construction for finalizer declarations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.core.finalizer_facade import validate_finalizer_context
from sase.core.finalizer_wire import (
    FINALIZER_WIRE_SCHEMA_VERSION,
    FinalizerAssignedBeadWire,
    FinalizerContextWire,
    FinalizerHandoffWire,
    FinalizerObligationWire,
    FinalizerPlanWire,
    finalizer_wire_to_json_dict,
)
from sase.finalizers.declaration_context_evidence import (
    build_commit_declaration_context,
)
from sase.finalizers.declaration_manifest import (
    context_requires_submission,
    manifest_template,
    now_iso,
)
from sase.finalizers.declaration_store import (
    FinalizerDeclarationError,
    HostRepositoryRecord,
    build_context_requirements,
    host_repository_records,
    repository_obligation_id,
)
from sase.llm_provider.commit_finalizer_config import resolve_finalizer_project_dir
from sase.llm_provider.commit_finalizer_raw_commits import (
    AbsorbedRawCommits,
    absorb_raw_local_commits,
)
from sase.llm_provider.commit_finalizer_state import (
    DirtyState,
    collect_dirty_state as collect_project_dirty_state,
)

if TYPE_CHECKING:
    from sase.finalizers.prepared_coverage import PreparedStarterCoverage


@dataclass(frozen=True)
class LiveFinalizerContext:
    payload: dict[str, Any]
    context: FinalizerContextWire
    host_records: tuple[HostRepositoryRecord, ...]


@dataclass(frozen=True)
class FinalContextPublication:
    """One published finalizer context artifact."""

    payload: dict[str, Any]
    context: FinalizerContextWire
    path: Path

    @property
    def submission_required(self) -> bool:
        return context_requires_submission(self.context)


def build_live_context(
    root: Path,
    *,
    command: str,
    plan: FinalizerPlanWire | None = None,
) -> LiveFinalizerContext:
    from sase.finalizers.declaration import (
        SASE_FINAL_TURN_NONCE_ENV,
        load_finalizer_plan,
    )

    plan = plan or load_finalizer_plan(root)
    run_id, agent_id, turn_nonce = _run_identity(
        root, command, nonce_env=SASE_FINAL_TURN_NONCE_ENV
    )
    # Absorb eligible raw local commits before dirty-state collection so the
    # staged changes enter the ordinary obligation and declaration path.
    # Never absorbs at execution time; there, only the backstop applies.
    absorbed = absorb_raw_local_commits(resolve_finalizer_project_dir(), root)
    dirty_state = _collect_dirty_state(root)
    # This reader is deliberately lock-free: publication already holds the
    # declaration lock, and taking the handoff lock here would reverse the
    # staging lock order. Atomic record replacement gives us one validated
    # staged identity without waiting on its writer.
    handoff = _handoff_from_staged_record(root)
    prepared_coverage = None
    prepared_eligible = False
    if handoff is not None and handoff.prepared_intent_ref:
        from sase.finalizers.prepared_coverage import (
            evaluate_prepared_starter_coverage_for_artifacts,
            prepared_coverage_omits_starter_submission,
        )

        prepared_coverage = evaluate_prepared_starter_coverage_for_artifacts(
            root,
            plan_digest=plan.plan_digest,
            obligation_ids=[
                repository_obligation_id(repo) for repo in dirty_state.repos
            ],
            run_id=run_id,
            agent_id=agent_id,
            workspace_id=(os.environ.get("SASE_WORKSPACE_NUM") or "").strip() or None,
        )
        prepared_eligible = prepared_coverage_omits_starter_submission(
            root, prepared_coverage
        )
    requirements, obligations = build_context_requirements(
        plan,
        dirty_state,
        handoff=handoff,
        prepared_coverage_eligible=prepared_eligible,
    )
    host_records = host_repository_records(dirty_state)
    assigned_bead = _assigned_bead_context(dirty_state, obligations)

    context = FinalizerContextWire(
        schema_version=FINALIZER_WIRE_SCHEMA_VERSION,
        run_id=run_id,
        agent_id=agent_id,
        turn_nonce=turn_nonce,
        plan_digest=plan.plan_digest,
        requirements=requirements,
        obligations=obligations,
        assigned_bead=assigned_bead,
        handoff=handoff,
    )
    context_digest = validate_finalizer_context(plan, context)
    context = replace(context, context_digest=context_digest)
    return LiveFinalizerContext(
        payload=_context_payload(
            plan,
            context,
            root=root,
            host_records=host_records,
            absorbed_raw_commits=absorbed,
            prepared_coverage=prepared_coverage,
        ),
        context=context,
        host_records=host_records,
    )


def _run_identity(root: Path, command: str, *, nonce_env: str) -> tuple[str, str, str]:
    from sase.agent.identity import resolve_local_agent_name

    run_id = (os.environ.get("SASE_AGENT_TIMESTAMP") or "").strip()
    identity_env = dict(os.environ)
    identity_env["SASE_ARTIFACTS_DIR"] = str(root)
    agent_id = resolve_local_agent_name(identity_env) or ""
    turn_nonce = (os.environ.get(nonce_env) or "").strip()
    missing: list[str] = []
    if not run_id:
        missing.append("SASE_AGENT_TIMESTAMP")
    if not agent_id:
        missing.append("SASE_AGENT_NAME or agent_meta.json name")
    if not turn_nonce:
        missing.append(nonce_env)
    if missing:
        raise FinalizerDeclarationError(
            f"{command} requires active finalizer turn metadata: " + ", ".join(missing),
            code="missing_turn_metadata",
        )
    return run_id, agent_id, turn_nonce


def _collect_dirty_state(root: Path) -> DirtyState:
    return collect_project_dirty_state(
        resolve_finalizer_project_dir(),
        artifact_root=root,
    )


def _handoff_from_staged_record(root: Path) -> FinalizerHandoffWire | None:
    from sase.agent.staged_handoff import StagedHandoffError, read_staged_handoff

    try:
        record = read_staged_handoff(str(root))
    except StagedHandoffError as exc:
        raise FinalizerDeclarationError(
            f"staged handoff state is invalid: {exc}",
            code="invalid_staged_handoff",
        ) from exc
    if record is None:
        return None

    payload = record.get("payload")
    if not isinstance(payload, Mapping):
        raise FinalizerDeclarationError(
            "staged handoff payload is malformed",
            code="invalid_staged_handoff",
        )
    prepared_intent_ref = payload.get("prepared_intent_ref")
    if prepared_intent_ref is not None and (
        not isinstance(prepared_intent_ref, str) or not prepared_intent_ref.strip()
    ):
        raise FinalizerDeclarationError(
            "staged prepared intent reference is malformed",
            code="invalid_staged_handoff",
        )
    return FinalizerHandoffWire(
        kind=str(record["kind"]),
        staged_ref=str(record["staged_id"]),
        successor_workspace=str(record["successor_workspace"]),
        carry_allowed=bool(record["carry_allowed"]),
        prepared_intent_ref=prepared_intent_ref,
    )


def _assigned_bead_context(
    dirty_state: DirtyState,
    obligations: list[FinalizerObligationWire],
) -> FinalizerAssignedBeadWire | None:
    bead_id = (os.environ.get("SASE_BEAD_ID") or "").strip()
    if not bead_id:
        return None

    primary_repo_id: str | None = None
    obligation_by_repo = {
        repository_obligation_id(repo): obligation
        for repo in dirty_state.repos
        for obligation in obligations
        if obligation.kind == "repository"
        and obligation.obligation_id == repository_obligation_id(repo)
    }
    for repo in dirty_state.repos:
        if repo.kind != "main":
            continue
        obligation = obligation_by_repo.get(repository_obligation_id(repo))
        if obligation is not None:
            primary_repo_id = obligation.obligation_id
            break

    return FinalizerAssignedBeadWire(
        bead_id=bead_id,
        primary_repo_obligation_id=primary_repo_id,
    )


def _context_payload(
    plan: FinalizerPlanWire,
    context: FinalizerContextWire,
    *,
    root: Path,
    host_records: tuple[HostRepositoryRecord, ...],
    absorbed_raw_commits: tuple[AbsorbedRawCommits, ...] = (),
    prepared_coverage: PreparedStarterCoverage | None = None,
) -> dict[str, Any]:
    requirement_by_id = {item.instance_id: item for item in context.requirements}
    selected = []
    for entry in plan.entries:
        requirement = requirement_by_id.get(entry.instance_id)
        selected.append(
            {
                "instance_id": entry.instance_id,
                "provider_ref": entry.provider_ref,
                "trigger": requirement.trigger if requirement else "not_triggered",
                "submission_required": (
                    requirement.submission_required if requirement else False
                ),
                "policy": finalizer_wire_to_json_dict(entry.policy),
            }
        )
    return {
        "schema_version": 1,
        "issued_at": now_iso(),
        "context": finalizer_wire_to_json_dict(context),
        "selected_instances": selected,
        "submission_required": context_requires_submission(context),
        "commit_declaration": build_commit_declaration_context(
            root=root,
            context=context,
            host_records=host_records,
            absorbed_raw_commits=absorbed_raw_commits,
            prepared_coverage=prepared_coverage,
        ),
        "manifest_template": manifest_template(context),
    }
