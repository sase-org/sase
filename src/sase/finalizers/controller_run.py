"""Host-owned finalizer controller orchestration and execution loop."""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import replace
from typing import Any

from sase.core.finalizer_wire import FinalizerInstanceResultWire
from sase.core.process_identity import process_identity_token
from sase.finalizers._controller_shared import (
    ensure_declaration_with_events,
    publish_aggregate,
    sync_instance_events,
)
from sase.finalizers.commit import BuiltinCommitFinalizerError
from sase.finalizers.config import FinalizerConfigDiagnostic
from sase.finalizers.controller_context import (
    FinalizerControllerError,
    bind_execution_context,
    cycle_fingerprint,
    entries_from_plan,
    pending_instance_ids,
    publish_final_context,
    should_skip_finalizers,
)
from sase.finalizers.controller_cycle import (
    MAX_CONTROLLER_CYCLES,
    execute_pending_entry,
)
from sase.finalizers.controller_results import (
    failed_result,
    record_instance_metrics,
    remember_result,
)
from sase.finalizers.executor import FinalizerExecutionContext
from sase.finalizers.ledger import InstanceLedger
from sase.finalizers.plan import (
    FinalizerPlanIntegrityError,
    authenticate_resolved_finalizer_plan_full,
)
from sase.finalizers.progress import ProgressJournal
from sase.finalizers.providers import BUILTIN_PROVIDER_REFS
from sase.finalizers.status_summary import FinalizerStatusTracker
from sase.llm_provider.types import ModelTier


def _journal_handoff_skip(artifacts_dir: str | None) -> None:
    """Best-effort record a handoff skip; silent without a dir and marker."""
    if not artifacts_dir:
        return
    if not os.environ.get("SASE_AGENT_TIMESTAMP"):
        return
    from sase.agent.pending_handoff import pending_handoff_kind

    kind = pending_handoff_kind(artifacts_dir)
    if kind is None:
        return
    reason = f"handoff:{kind}"
    try:
        ProgressJournal(artifacts_dir).record("phase_skipped", reason=reason)
    except Exception:
        pass
    try:
        FinalizerStatusTracker(artifacts_dir).mark_skipped(reason=reason)
    except Exception:
        pass


def _runner_fact() -> dict[str, Any]:
    """Return the runner identity fact for ``phase_started`` records."""
    pid = os.getpid()
    return {"pid": pid, "identity": process_identity_token(pid) or None}


def _bind_observed_context(
    artifacts_dir: str | None,
    plan: Any,
    publication: Any,
    journal: ProgressJournal,
    tracker: Any,
) -> FinalizerExecutionContext:
    """Bind an execution context carrying the shared journal and tracker."""
    context = bind_execution_context(artifacts_dir, plan, publication)
    try:
        return replace(context, journal=journal, tracker=tracker)
    except Exception:
        return context


def _remember_drift(
    drift_by_key: dict[tuple[str, str], FinalizerConfigDiagnostic],
    drift: tuple[FinalizerConfigDiagnostic, ...],
) -> None:
    for item in drift:
        drift_by_key[(item.code, item.path)] = item


def _project_drift_to_agent_meta(
    artifacts_dir: str,
    drift_by_key: dict[tuple[str, str], FinalizerConfigDiagnostic],
) -> None:
    """Best-effort surface sealed-config drift on ``agent_meta.json`` for ACE."""

    from sase.axe.run_agent_helpers import update_meta_field

    try:
        update_meta_field(
            artifacts_dir,
            "finalizers_drift",
            [
                {"code": item.code, "severity": item.severity, "message": item.message}
                for item in drift_by_key.values()
            ],
        )
    except Exception:
        pass


def run_finalizers(
    *,
    provider: Any,
    original_prompt: str,
    invoke_result: Any,
    model_tier: ModelTier,
    suppress_output: bool,
    model_override: str | None,
    artifacts_dir: str | None,
    options: Any = None,
    mode: str = "normal",
) -> Any:
    """Drive selected finalizers to a bounded fixed point.

    The built-in commit instance consumes the accepted final declaration and
    dispatches repository mutations through ``sase stitch create``. Later
    mutating executors can reactivate commit; declaration recovery and
    conflict repair keep separate one-shot budgets.
    """

    no_model = mode == "no_model"
    if not no_model and should_skip_finalizers(artifacts_dir):
        _journal_handoff_skip(artifacts_dir)
        return invoke_result

    journal = ProgressJournal(artifacts_dir)
    tracker = FinalizerStatusTracker(artifacts_dir)
    attempts_seen: dict[str, set[int]] = {}
    started_instances: set[str] = set()
    published: dict[str, Any] = {"status": "failed", "cycles": 0}

    drift_by_key: dict[tuple[str, str], FinalizerConfigDiagnostic] = {}
    try:
        authenticated = authenticate_resolved_finalizer_plan_full(artifacts_dir)
    except FinalizerPlanIntegrityError as exc:
        journal.record("phase_finished", status="failed", cycles=0)
        tracker.mark_settled(status="failed", reason=exc.code)
        raise FinalizerControllerError(str(exc), code=exc.code) from exc
    plan = authenticated.plan
    _remember_drift(drift_by_key, authenticated.drift)
    run_id = uuid.uuid4().hex
    runner = _runner_fact()
    journal.record(
        "phase_started",
        run_id=run_id,
        plan_digest=plan.plan_digest,
        mode=mode,
        runner=runner,
    )
    tracker.mark_declaring(run_id=run_id, plan_digest=plan.plan_digest, runner=runner)
    entries = entries_from_plan(plan)
    if not entries:
        publish_aggregate(
            artifacts_dir,
            [],
            "success",
            cycles=0,
            drift_by_key=drift_by_key,
            published=published,
        )
        journal.record("phase_finished", status="success", cycles=0)
        tracker.mark_settled(status="success")
        return invoke_result

    current_result = invoke_result
    results_by_id: dict[str, FinalizerInstanceResultWire] = {}
    ledgers: dict[str, InstanceLedger] = {}
    ran_non_commit: set[str] = set()
    fingerprints: set[str] = set()
    active_provider_ref: str | None = None
    active_instance_id: str | None = None
    active_started: float | None = None
    cycles = 0

    try:
        if no_model:
            _reject_no_model_ineligible_plan(entries, artifacts_dir)
        else:
            current_result = ensure_declaration_with_events(
                journal,
                provider=provider,
                invoke_result=current_result,
                model_tier=model_tier,
                suppress_output=suppress_output,
                model_override=model_override,
                artifacts_dir=artifacts_dir,
                options=options,
                original_prompt=original_prompt,
            )
        for cycle in range(1, MAX_CONTROLLER_CYCLES + 1):
            cycles = cycle
            journal.record("cycle_started", cycle=cycle)
            authenticated = authenticate_resolved_finalizer_plan_full(artifacts_dir)
            plan = authenticated.plan
            _remember_drift(drift_by_key, authenticated.drift)
            entries = entries_from_plan(plan)
            publication = publish_final_context(artifacts_dir=artifacts_dir)
            context = _bind_observed_context(
                artifacts_dir, plan, publication, journal, tracker
            )
            pending = pending_instance_ids(
                entries,
                publication.payload,
                results_by_id,
                ran_non_commit,
            )
            fingerprint = cycle_fingerprint(publication.context.context_digest, pending)
            if fingerprint in fingerprints:
                raise FinalizerControllerError(
                    "finalizer controller made no progress; dirty state and "
                    "pending instances did not change",
                    code="controller_no_progress",
                )
            fingerprints.add(fingerprint)
            if not pending:
                break

            progressed = False
            for entry in entries:
                instance_id = entry["instance_id"]
                if instance_id not in pending:
                    continue
                authenticated = authenticate_resolved_finalizer_plan_full(artifacts_dir)
                plan = authenticated.plan
                _remember_drift(drift_by_key, authenticated.drift)
                entries = entries_from_plan(plan)
                config = authenticated.config
                context = _bind_observed_context(
                    artifacts_dir, plan, publication, journal, tracker
                )
                provider_ref = entry["provider_ref"]
                instance = config.instances.get(instance_id)
                if instance is None:
                    raise FinalizerControllerError(
                        f"selected finalizer instance {instance_id!r} is not configured",
                        code="missing_instance",
                    )
                active_provider_ref = provider_ref
                active_instance_id = instance_id
                active_started = time.monotonic()
                current_result = execute_pending_entry(
                    entry=entry,
                    instance=instance,
                    config=config,
                    context=context,
                    ledgers=ledgers,
                    journal=journal,
                    tracker=tracker,
                    provider=provider,
                    invoke_result=current_result,
                    model_tier=model_tier,
                    suppress_output=suppress_output,
                    model_override=model_override,
                    options=options,
                    artifacts_dir=artifacts_dir,
                    original_prompt=original_prompt,
                    no_model=no_model,
                    results_by_id=results_by_id,
                    attempts_seen=attempts_seen,
                    started_instances=started_instances,
                    ran_non_commit=ran_non_commit,
                    drift_by_key=drift_by_key,
                    published=published,
                    cycles=cycles,
                )
                progressed = True

            if not progressed:
                raise FinalizerControllerError(
                    "finalizer controller made no progress; no executor ran",
                    code="controller_no_progress",
                )
            authenticated = authenticate_resolved_finalizer_plan_full(artifacts_dir)
            plan = authenticated.plan
            _remember_drift(drift_by_key, authenticated.drift)
            entries = entries_from_plan(plan)
            publication = publish_final_context(artifacts_dir=artifacts_dir)
            context = _bind_observed_context(
                artifacts_dir, plan, publication, journal, tracker
            )
            if not pending_instance_ids(
                entries,
                publication.payload,
                results_by_id,
                ran_non_commit,
            ):
                break
        else:
            raise FinalizerControllerError(
                f"finalizer controller exceeded {MAX_CONTROLLER_CYCLES} cycles "
                "without reaching a fixed point",
                code="controller_cycle_limit",
            )
        publish_aggregate(
            artifacts_dir,
            list(results_by_id.values()),
            "success",
            cycles=cycles,
            drift_by_key=drift_by_key,
            published=published,
        )
    except FinalizerPlanIntegrityError as exc:
        raise FinalizerControllerError(str(exc), code=exc.code) from exc
    except BuiltinCommitFinalizerError as exc:
        if exc.invoke_result is not None:
            current_result = exc.invoke_result
        remember_result(results_by_id, exc.result)
        if active_instance_id is not None:
            sync_instance_events(
                journal,
                tracker,
                active_instance_id,
                exc.result,
                attempts_seen,
                started_instances,
            )
        if active_provider_ref is not None and active_instance_id is not None:
            record_instance_metrics(
                active_provider_ref,
                active_instance_id,
                exc.result.status,
                len(exc.result.attempts),
                time.monotonic() - (active_started or time.monotonic()),
            )
        publish_aggregate(
            artifacts_dir,
            list(results_by_id.values()),
            exc.result.status
            if exc.result.status in {"failed", "refused"}
            else "failed",
            cycles=cycles,
            drift_by_key=drift_by_key,
            published=published,
        )
        raise
    except FinalizerControllerError as exc:
        if exc.code == "plan_integrity_failed":
            raise
        instance_id = active_instance_id or (
            entries[0]["instance_id"] if entries else "controller"
        )
        failed = failed_result(instance_id, exc.code, str(exc))
        remember_result(results_by_id, failed)
        sync_instance_events(
            journal, tracker, instance_id, failed, attempts_seen, started_instances
        )
        publish_aggregate(
            artifacts_dir,
            list(results_by_id.values()),
            "failed",
            cycles=cycles,
            drift_by_key=drift_by_key,
            published=published,
        )
        raise
    except Exception as exc:
        if getattr(exc, "code", None) == "plan_integrity_failed":
            raise FinalizerControllerError(
                str(exc),
                code="plan_integrity_failed",
            ) from exc
        if not results_by_id or next(reversed(results_by_id.values())).status == (
            "success"
        ):
            instance_id = active_instance_id or entries[0]["instance_id"]
            failed = failed_result(
                instance_id,
                "controller_exception",
                f"{type(exc).__name__}: {exc}",
            )
            remember_result(results_by_id, failed)
            sync_instance_events(
                journal,
                tracker,
                instance_id,
                failed,
                attempts_seen,
                started_instances,
            )
        publish_aggregate(
            artifacts_dir,
            list(results_by_id.values()),
            "failed",
            cycles=cycles,
            drift_by_key=drift_by_key,
            published=published,
        )
        raise
    finally:
        if artifacts_dir and drift_by_key:
            _project_drift_to_agent_meta(artifacts_dir, drift_by_key)
        journal.record(
            "phase_finished", status=published["status"], cycles=published["cycles"]
        )
        tracker.mark_settled(status=published["status"])

    return current_result


def _reject_no_model_ineligible_plan(
    entries: tuple[dict[str, Any], ...],
    artifacts_dir: str | None,
) -> None:
    from sase.finalizers.declaration import (
        final_submission_is_current,
        publish_final_context,
    )

    publication = publish_final_context(artifacts_dir=artifacts_dir)
    if publication.submission_required and not final_submission_is_current(
        artifacts_dir=artifacts_dir
    ):
        raise FinalizerControllerError(
            "no-model host completion requires an accepted declaration",
            code="no_model_declaration_missing",
        )
    for entry in entries:
        if entry["provider_ref"] not in BUILTIN_PROVIDER_REFS:
            raise FinalizerControllerError(
                f"finalizer {entry['instance_id']!r} ({entry['provider_ref']}) "
                "does not support no-model host completion",
                code="no_model_unsupported_executor",
            )
