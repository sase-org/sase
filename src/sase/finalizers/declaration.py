"""Turn-bound finalizer declaration context and submission coordination.

Context publication and submission acceptance share one lock order so a
successful ``sase final submit`` cannot land against an already stale
context:

1. the in-process declaration mutex (threads in one interpreter)
2. ``final_declaration.lock`` flock (separate processes)

Both ``publish_final_context`` and ``submit_final_manifest`` take that
pair for the whole critical section. Submit re-reads the on-disk context
immediately before accepting so a lost race still fails closed.

This module remains the public facade. Manifest mechanics and recovery-turn
orchestration live in focused sibling modules.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, replace
import os
from pathlib import Path
import secrets
from typing import Any

from sase.agent.identity import resolve_local_agent_name
from sase.agent.staged_handoff import StagedHandoffError, read_staged_handoff
from sase.core.finalizer_facade import (
    validate_finalizer_context,
    validate_finalizer_submission,
)
from sase.core.finalizer_wire import (
    FINALIZER_WIRE_SCHEMA_VERSION,
    FinalizerAssignedBeadWire,
    FinalizerContextWire,
    FinalizerHandoffWire,
    FinalizerObligationWire,
    FinalizerPlanWire,
    finalizer_wire_to_json_dict,
)
from sase.finalizers.declaration_format import format_context_pretty
from sase.finalizers.declaration_deferrals import adjudicate_commit_deferrals
from sase.finalizers.declaration_context_evidence import (
    build_commit_declaration_context,
)
from sase.finalizers.commit_carry import carry_action_allowed_for_handoff
from sase.finalizers.prepared_coverage import (
    PreparedStarterCoverage,
    evaluate_prepared_starter_coverage_for_artifacts,
    prepared_coverage_omits_starter_submission,
)
from sase.finalizers.declaration_manifest import (
    FINAL_CONTEXT_FILENAME,
    FINAL_SUBMISSION_ATTEMPTS_FILENAME,
    FINAL_SUBMISSION_FILENAME,
    append_attempt_record_locked as _append_attempt_record_locked,
    context_requires_submission as _context_requires_submission,
    load_latest_finalizer_context,
    load_latest_finalizer_submission,
    manifest_template as _manifest_template,
    normalize_submission_envelope,
    now_iso as _now_iso,
    read_final_manifest_from_path as _read_final_manifest_from_path,
    safe_value_digest as _safe_value_digest,
    validate_provider_payloads,
)
from sase.finalizers.declaration_recovery import (
    FINAL_DECLARATION_RECOVERY_EVIDENCE_FILENAME,
    FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME,
    FINAL_DECLARATION_RECOVERY_RESPONSE_FILENAME,
    ensure_final_declaration_or_recover,
)
from sase.finalizers.declaration_store import (
    FINAL_CONTEXT_HOST_FILENAME,
    FINAL_DECLARATION_LOCK_FILENAME,
    FINAL_SUBMISSION_HOST_FILENAME,
    FinalizerDeclarationError,
    HostRepositoryRecord,
    accepted_context_from_submission,
    acquire_declaration_locks,
    build_context_requirements as _build_context_requirements,
    host_repository_records as _host_repository_records,
    load_accepted_host_repositories,
    read_host_repository_file as _read_host_repository_file,
    repository_obligation_id,
    repository_state_digest,
    write_host_repository_file as _write_host_repository_file,
    write_json_atomic as _write_json_atomic,
)
from sase.finalizers.plan import (
    FinalizerPlanIntegrityError,
    authenticate_resolved_finalizer_plan,
)
from sase.llm_provider.commit_finalizer_config import resolve_finalizer_project_dir
from sase.llm_provider.commit_finalizer_raw_commits import (
    AbsorbedRawCommits,
    absorb_raw_local_commits,
)
from sase.llm_provider.commit_finalizer_state import collect_dirty_state
from sase.llm_provider.commit_finalizer_types import DirtyState
from sase.telemetry.metrics import FINALIZER_SELECTED

SASE_FINAL_TURN_NONCE_ENV = "SASE_FINAL_TURN_NONCE"


@dataclass(frozen=True)
class FinalContextPublication:
    """One published finalizer context artifact."""

    payload: dict[str, Any]
    context: FinalizerContextWire
    path: Path

    @property
    def submission_required(self) -> bool:
        return _context_requires_submission(self.context)


@dataclass(frozen=True)
class _LiveFinalizerContext:
    payload: dict[str, Any]
    context: FinalizerContextWire
    host_records: tuple[HostRepositoryRecord, ...]


def _declaration_sync_hook(_point: str) -> None:
    """Deterministic interleaving seam; production is a no-op."""


def _verdict_provenance(envelope: Mapping[str, Any]) -> Any:
    """Record receipt provenance for an accepted declaration, nonblocking.

    Host completion threads eligibility evidence through its own receipt;
    ordinary ``sase final submit`` carries no covering receipt and records
    ``unverified`` instead of refusing the submission.
    """

    evidence = envelope.get("verdict_receipt")
    if isinstance(evidence, Mapping) and evidence.get("receipt_id"):
        return dict(evidence)
    return "unverified"


@contextmanager
def hold_finalizer_declaration_lock(root: Path) -> Iterator[None]:
    """Hold the documented declaration lock order for *root*."""

    _declaration_sync_hook("before_declaration_lock")
    with acquire_declaration_locks(root):
        _declaration_sync_hook("holding_declaration_lock")
        yield


def mint_finalizer_turn_nonce() -> str:
    """Mint and publish a nonce for the active provider turn."""

    nonce = secrets.token_urlsafe(32)
    os.environ[SASE_FINAL_TURN_NONCE_ENV] = nonce
    return nonce


def publish_final_context(
    *,
    artifacts_dir: str | None = None,
) -> FinalContextPublication:
    """Recompute, validate, and atomically publish the current finalizer context."""

    root = require_artifacts_dir(artifacts_dir, "sase final context")
    with hold_finalizer_declaration_lock(root):
        live = _build_live_context(root, command="sase final context")
        _record_selected_metrics(live.payload)
        _declaration_sync_hook("before_context_write")
        path = root / FINAL_CONTEXT_FILENAME
        _write_json_atomic(path, live.payload)
        _write_host_repository_file(
            root / FINAL_CONTEXT_HOST_FILENAME,
            context_digest=live.context.context_digest or "",
            records=live.host_records,
        )
        return FinalContextPublication(
            payload=live.payload,
            context=live.context,
            path=path,
        )


def submit_final_manifest(
    manifest: Mapping[str, Any],
    *,
    artifacts_dir: str | None = None,
    _synthesized_provenance: Mapping[str, Any] | None = None,
    _only_if_absent: bool = False,
) -> dict[str, Any]:
    """Validate and atomically publish one finalizer declaration manifest."""

    root = require_artifacts_dir(artifacts_dir, "sase final submit")
    content_digest = _safe_value_digest(manifest)

    with hold_finalizer_declaration_lock(root):
        submission_path = root / FINAL_SUBMISSION_FILENAME
        if _only_if_absent and (
            submission_path.exists() or submission_path.is_symlink()
        ):
            raise FinalizerDeclarationError(
                "a finalizer submission already exists; preserve and validate it "
                "instead of replacing it with synthesized carry",
                code="submission_already_exists",
            )
        host_records = _read_host_repository_file(root / FINAL_CONTEXT_HOST_FILENAME)
        try:
            plan = load_finalizer_plan(root)
            context = load_latest_finalizer_context(root)
            envelope = normalize_submission_envelope(manifest)
            if envelope.get("context_digest") != context.context_digest:
                raise FinalizerDeclarationError(
                    "finalizer context changed before the declaration could be "
                    "accepted; rerun `sase final context` and submit a manifest "
                    "built from the refreshed template",
                    code="stale_final_context",
                )
            validation = validate_finalizer_submission(plan, context, envelope)
            validate_provider_payloads(
                plan, context, envelope, host_records=host_records
            )
        except FinalizerDeclarationError as exc:
            _append_attempt_record_locked(
                root,
                accepted=False,
                code=exc.code,
                message=str(exc),
                content_digest=content_digest,
            )
            raise
        except Exception as exc:
            wrapped = FinalizerDeclarationError(str(exc), code="core_validation_failed")
            _append_attempt_record_locked(
                root,
                accepted=False,
                code=wrapped.code,
                message=str(wrapped),
                content_digest=content_digest,
            )
            raise wrapped from exc

        _declaration_sync_hook("submit_after_validate")
        current = load_latest_finalizer_context(root)
        if current.context_digest != context.context_digest:
            stale = FinalizerDeclarationError(
                "finalizer context changed before the declaration could be accepted",
                code="stale_final_context",
            )
            _append_attempt_record_locked(
                root,
                accepted=False,
                code=stale.code,
                message=str(stale),
                content_digest=content_digest,
            )
            raise stale

        host_records = _read_host_repository_file(root / FINAL_CONTEXT_HOST_FILENAME)
        live = _build_live_context(
            root,
            command="sase final submit",
            plan=plan,
        )
        if (
            live.context.context_digest != current.context_digest
            or _host_repository_record_set(live.host_records)
            != _host_repository_record_set(host_records)
        ):
            stale = FinalizerDeclarationError(
                "finalizer context is stale because repository state changed before "
                "the declaration could be accepted; rerun `sase final context` and "
                "submit a manifest built from the refreshed template",
                code="stale_final_context",
            )
            _append_attempt_record_locked(
                root,
                accepted=False,
                code=stale.code,
                message=str(stale),
                content_digest=content_digest,
            )
            raise stale

        if _synthesized_provenance is not None:
            if not _only_if_absent or not carry_action_allowed_for_handoff(
                current.handoff
            ):
                raise FinalizerDeclarationError(
                    "host-synthesized carry requires a legal unprepared staged handoff",
                    code="synthesized_carry_invalid",
                )

        try:
            accepted_deferrals = adjudicate_commit_deferrals(
                plan,
                current,
                envelope,
                root=root,
                host_records=host_records,
            )
        except FinalizerDeclarationError as exc:
            _append_attempt_record_locked(
                root,
                accepted=False,
                code=exc.code,
                message=str(exc),
                content_digest=content_digest,
            )
            raise

        _declaration_sync_hook("before_submit_accept")
        submission_payload = {
            "schema_version": 1,
            "accepted_at": _now_iso(),
            "accepted_context": finalizer_wire_to_json_dict(current),
            "submission": envelope,
            "validation": finalizer_wire_to_json_dict(validation),
            "accepted_deferrals": [item.to_json() for item in accepted_deferrals],
            "verdict_provenance": _verdict_provenance(envelope),
        }
        if _synthesized_provenance is not None:
            submission_payload["synthesized"] = dict(_synthesized_provenance)
        _append_attempt_record_locked(
            root,
            accepted=True,
            code="accepted",
            message="accepted finalizer declaration",
            content_digest=content_digest,
            submission_digest=validation.submission_digest,
            accepted_instances=tuple(validation.accepted_instances),
        )
        _write_json_atomic(root / FINAL_SUBMISSION_FILENAME, submission_payload)
        _write_host_repository_file(
            root / FINAL_SUBMISSION_HOST_FILENAME,
            context_digest=current.context_digest or "",
            records=host_records,
        )
        return submission_payload


def synthesize_carry_declaration(
    publication: FinalContextPublication,
    *,
    artifacts_dir: str | None = None,
) -> dict[str, Any] | None:
    """Persist host-authored carry when a dirty inheriting handoff has no submission."""

    context = publication.context
    repository_ids = [
        obligation.obligation_id
        for obligation in context.obligations
        if obligation.kind == "repository"
    ]
    if (
        publication.submission_required
        or not repository_ids
        or not carry_action_allowed_for_handoff(context.handoff)
    ):
        return None

    manifest = deepcopy(publication.payload.get("manifest_template"))
    if not isinstance(manifest, dict):
        raise FinalizerDeclarationError(
            "finalizer context has no usable manifest template",
            code="malformed_final_context",
        )
    payloads = manifest.get("payloads")
    if not isinstance(payloads, list):
        raise FinalizerDeclarationError(
            "finalizer manifest template payloads are malformed",
            code="malformed_final_context",
        )

    carried: set[str] = set()
    for item in payloads:
        if not isinstance(item, Mapping):
            continue
        payload = item.get("payload")
        if not isinstance(payload, Mapping):
            continue
        repositories = payload.get("repositories")
        if not isinstance(repositories, list):
            continue
        for decision in repositories:
            if not isinstance(decision, dict):
                continue
            repo_id = decision.get("repo_id")
            if not isinstance(repo_id, str) or repo_id not in repository_ids:
                continue
            decision["action"] = "carry"
            decision.pop("message", None)
            decision.pop("bead_action", None)
            carried.add(repo_id)
    if carried != set(repository_ids):
        raise FinalizerDeclarationError(
            "manifest template does not cover every repository eligible for carry",
            code="malformed_final_context",
        )

    handoff = context.handoff
    if handoff is None:
        return None
    provenance = {
        "kind": "handoff_carry",
        "source": "host",
        "staged_ref": handoff.staged_ref,
    }
    return submit_final_manifest(
        manifest,
        artifacts_dir=artifacts_dir,
        _synthesized_provenance=provenance,
        _only_if_absent=True,
    )


def read_final_manifest_from_path(path: str) -> Mapping[str, Any]:
    """Read one JSON manifest from a path or stdin marker."""

    return _read_final_manifest_from_path(
        path,
        record_attempt=_record_attempt_best_effort,
    )


def final_submission_is_current(*, artifacts_dir: str | None = None) -> bool:
    """Return whether the latest accepted submission satisfies the latest context."""

    root = require_artifacts_dir(artifacts_dir, "finalizer declaration check")
    with hold_finalizer_declaration_lock(root):
        plan = load_finalizer_plan(root)
        context = load_latest_finalizer_context(root)
        submission_path = root / FINAL_SUBMISSION_FILENAME
        if not (submission_path.exists() or submission_path.is_symlink()):
            return not _context_requires_submission(context)
        try:
            submission = load_latest_finalizer_submission(root)
            envelope = normalize_submission_envelope(submission["submission"])
            validate_finalizer_submission(plan, context, envelope)
            host_records = load_accepted_host_repositories(root)
            validate_provider_payloads(
                plan, context, envelope, host_records=host_records
            )
            adjudicate_commit_deferrals(
                plan,
                context,
                envelope,
                root=root,
                host_records=host_records,
            )
        except Exception:
            return False
        return True


def require_artifacts_dir(value: str | None, command: str) -> Path:
    raw = value or os.environ.get("SASE_ARTIFACTS_DIR")
    if not raw:
        raise FinalizerDeclarationError(
            f"{command} requires SASE_ARTIFACTS_DIR",
            code="missing_artifacts_dir",
        )
    return Path(raw).expanduser().resolve(strict=False)


def load_finalizer_plan(root: Path) -> FinalizerPlanWire:
    try:
        return authenticate_resolved_finalizer_plan(str(root))
    except FinalizerPlanIntegrityError as exc:
        raise FinalizerDeclarationError(str(exc), code=exc.code) from exc


def _run_identity(root: Path, command: str) -> tuple[str, str, str]:
    run_id = (os.environ.get("SASE_AGENT_TIMESTAMP") or "").strip()
    identity_env = dict(os.environ)
    identity_env["SASE_ARTIFACTS_DIR"] = str(root)
    agent_id = resolve_local_agent_name(identity_env) or ""
    turn_nonce = (os.environ.get(SASE_FINAL_TURN_NONCE_ENV) or "").strip()
    missing: list[str] = []
    if not run_id:
        missing.append("SASE_AGENT_TIMESTAMP")
    if not agent_id:
        missing.append("SASE_AGENT_NAME or agent_meta.json name")
    if not turn_nonce:
        missing.append(SASE_FINAL_TURN_NONCE_ENV)
    if missing:
        raise FinalizerDeclarationError(
            f"{command} requires active finalizer turn metadata: " + ", ".join(missing),
            code="missing_turn_metadata",
        )
    return run_id, agent_id, turn_nonce


def _collect_dirty_state(root: Path) -> DirtyState:
    return collect_dirty_state(
        resolve_finalizer_project_dir(),
        artifact_root=root,
    )


def _build_live_context(
    root: Path,
    *,
    command: str,
    plan: FinalizerPlanWire | None = None,
) -> _LiveFinalizerContext:
    plan = plan or load_finalizer_plan(root)
    run_id, agent_id, turn_nonce = _run_identity(root, command)
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
    requirements, obligations = _build_context_requirements(
        plan,
        dirty_state,
        handoff=handoff,
        prepared_coverage_eligible=prepared_eligible,
    )
    host_records = _host_repository_records(dirty_state)
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
    return _LiveFinalizerContext(
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


def _handoff_from_staged_record(root: Path) -> FinalizerHandoffWire | None:
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


def _host_repository_record_set(
    records: tuple[HostRepositoryRecord, ...],
) -> frozenset[tuple[str, str, str, str]]:
    # `head` is intentionally excluded: a foreign commit landing on a shared
    # store between context and submit must not make the declaration stale.
    return frozenset(
        (record.obligation_id, record.kind, record.name, record.path)
        for record in records
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
        "issued_at": _now_iso(),
        "context": finalizer_wire_to_json_dict(context),
        "selected_instances": selected,
        "submission_required": _context_requires_submission(context),
        "commit_declaration": build_commit_declaration_context(
            root=root,
            context=context,
            host_records=host_records,
            absorbed_raw_commits=absorbed_raw_commits,
            prepared_coverage=prepared_coverage,
        ),
        "manifest_template": _manifest_template(context),
    }


def _record_selected_metrics(payload: Mapping[str, Any]) -> None:
    selected = payload.get("selected_instances")
    if not isinstance(selected, list):
        return
    for item in selected:
        if not isinstance(item, Mapping):
            continue
        instance_id = item.get("instance_id")
        provider_ref = item.get("provider_ref")
        trigger = item.get("trigger")
        if not (
            isinstance(instance_id, str)
            and isinstance(provider_ref, str)
            and isinstance(trigger, str)
        ):
            continue
        FINALIZER_SELECTED.labels(
            provider=provider_ref,
            instance=instance_id,
            trigger=trigger,
        ).inc()


def _record_attempt_best_effort(
    *,
    code: str,
    message: str,
    content_digest: str,
) -> None:
    try:
        root = require_artifacts_dir(None, "sase final submit")
        with hold_finalizer_declaration_lock(root):
            _append_attempt_record_locked(
                root,
                accepted=False,
                code=code,
                message=message,
                content_digest=content_digest,
            )
    except Exception:
        return


__all__ = [
    "FINAL_CONTEXT_FILENAME",
    "FINAL_CONTEXT_HOST_FILENAME",
    "FINAL_DECLARATION_LOCK_FILENAME",
    "FINAL_DECLARATION_RECOVERY_EVIDENCE_FILENAME",
    "FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME",
    "FINAL_DECLARATION_RECOVERY_RESPONSE_FILENAME",
    "FINAL_SUBMISSION_ATTEMPTS_FILENAME",
    "FINAL_SUBMISSION_FILENAME",
    "FINAL_SUBMISSION_HOST_FILENAME",
    "FinalContextPublication",
    "FinalizerDeclarationError",
    "HostRepositoryRecord",
    "SASE_FINAL_TURN_NONCE_ENV",
    "accepted_context_from_submission",
    "ensure_final_declaration_or_recover",
    "final_submission_is_current",
    "format_context_pretty",
    "hold_finalizer_declaration_lock",
    "load_accepted_host_repositories",
    "load_finalizer_plan",
    "load_latest_finalizer_context",
    "load_latest_finalizer_submission",
    "mint_finalizer_turn_nonce",
    "normalize_submission_envelope",
    "publish_final_context",
    "read_final_manifest_from_path",
    "repository_obligation_id",
    "repository_state_digest",
    "require_artifacts_dir",
    "submit_final_manifest",
    "synthesize_carry_declaration",
    "validate_provider_payloads",
]
