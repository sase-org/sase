from __future__ import annotations

import pytest

from sase.core.finalizer_facade import (
    aggregate_finalizer_outcomes,
    authenticate_finalizer_plan,
    finalizer_context_digest,
    finalizer_json_digest,
    finalizer_plan_digest,
    finalizer_provider_spec_digest,
    finalizer_wire_schema_version,
    resolve_finalizer_plan,
    validate_finalizer_context,
    validate_finalizer_plan,
    validate_finalizer_provider_spec,
    validate_finalizer_submission,
)
from sase.core.finalizer_wire import (
    FINALIZER_WIRE_SCHEMA_VERSION,
    FinalizerAttemptWire,
    FinalizerContextWire,
    FinalizerDeferralWire,
    FinalizerInstancePolicyWire,
    FinalizerInstanceResultWire,
    FinalizerInstanceSpecWire,
    FinalizerObligationWire,
    FinalizerPayloadRequirementWire,
    FinalizerPlanInputWire,
    FinalizerProviderSpecWire,
    FinalizerSubmissionEnvelopeWire,
    FinalizerSubmissionPayloadWire,
    finalizer_add,
)


pytestmark = pytest.mark.contract


def _commit_instance() -> FinalizerInstanceSpecWire:
    return FinalizerInstanceSpecWire(
        schema_version=FINALIZER_WIRE_SCHEMA_VERSION,
        instance_id="commit",
        provider_ref="builtin@commit",
        policy=FinalizerInstancePolicyWire(max_attempts=2),
    )


def test_finalizer_facade_resolves_plan_and_validates_submission() -> None:
    provider = FinalizerProviderSpecWire(
        schema_version=FINALIZER_WIRE_SCHEMA_VERSION,
        provider_ref="builtin@commit",
        capabilities=["requires_submission", "mutates_repository"],
    )

    validate_finalizer_provider_spec(provider)
    assert len(finalizer_provider_spec_digest(provider)) == 64

    plan = resolve_finalizer_plan(
        FinalizerPlanInputWire(
            schema_version=FINALIZER_WIRE_SCHEMA_VERSION,
            instances=[_commit_instance()],
            defaults=[],
            selectors=[finalizer_add("commit")],
        )
    )

    assert finalizer_wire_schema_version() == FINALIZER_WIRE_SCHEMA_VERSION
    assert [entry.instance_id for entry in plan.entries] == ["commit"]
    assert plan.plan_digest == finalizer_plan_digest(plan)
    assert validate_finalizer_plan(plan) == plan.plan_digest
    assert authenticate_finalizer_plan(plan, plan.plan_digest) == plan.plan_digest
    with pytest.raises(ValueError, match="expected plan digest"):
        authenticate_finalizer_plan(plan, "0" * 64)

    context = FinalizerContextWire(
        schema_version=FINALIZER_WIRE_SCHEMA_VERSION,
        run_id="run-1",
        agent_id="agent-1",
        turn_nonce="nonce-1",
        plan_digest=plan.plan_digest,
        requirements=[
            FinalizerPayloadRequirementWire(
                instance_id="commit",
                trigger="dirty_repository",
                submission_required=True,
            )
        ],
        obligations=[
            FinalizerObligationWire(
                obligation_id="repo:primary",
                kind="repository",
                display_name="primary",
                paths=["."],
            )
        ],
    )
    context_digest = validate_finalizer_context(plan, context)
    assert context_digest == finalizer_context_digest(context)

    payload = {"decision": "commit", "message": "adopt finalizer protocol"}
    validation = validate_finalizer_submission(
        plan,
        context,
        FinalizerSubmissionEnvelopeWire(
            schema_version=FINALIZER_WIRE_SCHEMA_VERSION,
            run_id="run-1",
            agent_id="agent-1",
            turn_nonce="nonce-1",
            plan_digest=plan.plan_digest,
            context_digest=context_digest,
            payloads=[
                FinalizerSubmissionPayloadWire(
                    instance_id="commit",
                    payload=payload,
                    payload_digest=finalizer_json_digest(payload),
                )
            ],
        ),
    )
    assert validation.accepted_instances == ["commit"]
    assert len(validation.submission_digest) == 64


def test_finalizer_facade_aggregates_instance_outcomes() -> None:
    aggregate = aggregate_finalizer_outcomes(
        [
            FinalizerInstanceResultWire(instance_id="lint", status="success"),
            FinalizerInstanceResultWire(
                instance_id="commit",
                status="refused",
                refusal_reason="No attributable repository changes",
                attempts=[
                    FinalizerAttemptWire(
                        attempt=1,
                        status="refused",
                        diagnostic_code="commit_refused",
                    )
                ],
            ),
        ]
    )

    assert aggregate.status == "refused"
    assert [instance.instance_id for instance in aggregate.instances] == [
        "lint",
        "commit",
    ]
    assert aggregate.diagnostics[0].instance_id == "commit"


def test_finalizer_facade_round_trips_deferred_instance_result() -> None:
    aggregate = aggregate_finalizer_outcomes(
        [
            FinalizerInstanceResultWire(instance_id="lint", status="success"),
            FinalizerInstanceResultWire(
                instance_id="commit",
                status="deferred",
                deferral=FinalizerDeferralWire(
                    reason="foreign_work",
                    paths=["sase/repos/linked/sase-core"],
                ),
            ),
        ]
    )

    assert aggregate.status == "deferred"
    commit = next(
        instance for instance in aggregate.instances if instance.instance_id == "commit"
    )
    assert commit.deferral is not None
    assert commit.deferral.reason == "foreign_work"
    assert commit.deferral.paths == ["sase/repos/linked/sase-core"]


def test_finalizer_facade_all_skipped_and_all_failed_aggregation() -> None:
    skipped = aggregate_finalizer_outcomes(
        [
            FinalizerInstanceResultWire(instance_id="lint", status="skipped"),
            FinalizerInstanceResultWire(instance_id="audit", status="skipped"),
        ]
    )
    assert skipped.status == "success"
    assert skipped.diagnostics == []

    failed = aggregate_finalizer_outcomes(
        [
            FinalizerInstanceResultWire(
                instance_id="lint",
                status="failed",
                attempts=[
                    FinalizerAttemptWire(
                        attempt=1, status="failed", diagnostic_code="command_failed"
                    )
                ],
            ),
            FinalizerInstanceResultWire(
                instance_id="audit",
                status="failed",
                attempts=[
                    FinalizerAttemptWire(
                        attempt=1, status="failed", diagnostic_code="execute_failed"
                    )
                ],
            ),
        ]
    )
    assert failed.status == "failed"
    assert failed.diagnostics[0].instance_id == "lint"
