"""Beta-gated finalizer controller entry point."""

from __future__ import annotations

from typing import Any

from sase.core.finalizer_wire import (
    FinalizerAttemptWire,
    FinalizerDiagnosticWire,
    FinalizerInstanceResultWire,
    finalizer_wire_to_json_dict,
)
from sase.finalizers.artifacts import write_finalizer_result
from sase.finalizers.config import load_finalizer_config
from sase.finalizers.executor import (
    FinalizerExecutionContext,
    execute_non_commit_finalizer,
)
from sase.finalizers.plan import load_persisted_finalizer_plan
from sase.finalizers.providers import BUILTIN_COMMIT_PROVIDER_REF
from sase.llm_provider.types import ModelTier


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
) -> Any:
    """Run the beta finalizer plan.

    This extension-runtime phase can execute non-mutating selected providers.
    The built-in commit instance still delegates to the legacy reconciler until
    the later generic reconciliation phase replaces that compatibility branch.
    """

    entries, plan_digest = _selected_entries(artifacts_dir)
    if not entries:
        return invoke_result

    config = load_finalizer_config()
    context = FinalizerExecutionContext(
        artifacts_dir=artifacts_dir,
        plan_digest=plan_digest,
    )
    current_result = invoke_result
    instance_results: list[FinalizerInstanceResultWire] = []
    try:
        for entry in entries:
            instance_id = entry["instance_id"]
            provider_ref = entry["provider_ref"]
            instance = config.instances.get(instance_id)
            if instance is None:
                raise RuntimeError(
                    f"selected finalizer instance {instance_id!r} is not configured"
                )
            if provider_ref == BUILTIN_COMMIT_PROVIDER_REF:
                current_result = _run_legacy_commit_finalizer(
                    provider=provider,
                    original_prompt=original_prompt,
                    invoke_result=current_result,
                    model_tier=model_tier,
                    suppress_output=suppress_output,
                    model_override=model_override,
                    artifacts_dir=artifacts_dir,
                    options=options,
                )
                instance_results.append(_success_result(instance_id))
                continue

            result = execute_non_commit_finalizer(instance, config, context)
            instance_results.append(result)
            if result.status != "success":
                _write_aggregate_result(artifacts_dir, instance_results, "failed")
                message = _result_failure_message(result)
                raise RuntimeError(message)
    except Exception as exc:
        if not instance_results or instance_results[-1].status == "success":
            instance_results.append(
                _failed_result(
                    instance_id=entries[min(len(instance_results), len(entries) - 1)][
                        "instance_id"
                    ],
                    message=f"{type(exc).__name__}: {exc}",
                )
            )
        _write_aggregate_result(artifacts_dir, instance_results, "failed")
        raise

    _write_aggregate_result(artifacts_dir, instance_results, "success")
    return current_result


def _selected_entries(
    artifacts_dir: str | None,
) -> tuple[tuple[dict[str, Any], ...], str | None]:
    payload = load_persisted_finalizer_plan(artifacts_dir)
    if not payload:
        return (
            (
                {
                    "instance_id": "commit",
                    "provider_ref": BUILTIN_COMMIT_PROVIDER_REF,
                    "resolved_index": 0,
                },
            ),
            None,
        )
    plan = payload.get("plan")
    if not isinstance(plan, dict):
        return (), None
    entries = plan.get("entries")
    if not isinstance(entries, list):
        return (), None
    selected: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        instance_id = entry.get("instance_id")
        provider_ref = entry.get("provider_ref")
        if (
            isinstance(instance_id, str)
            and instance_id
            and isinstance(provider_ref, str)
            and provider_ref
        ):
            selected.append(
                {
                    "instance_id": instance_id,
                    "provider_ref": provider_ref,
                    "resolved_index": int(entry.get("resolved_index", len(selected))),
                }
            )
    selected.sort(key=lambda item: int(item["resolved_index"]))
    plan_digest = plan.get("plan_digest")
    return tuple(selected), plan_digest if isinstance(plan_digest, str) else None


def _run_legacy_commit_finalizer(**kwargs: Any) -> Any:
    from sase.llm_provider.commit_finalizer import run_commit_finalizer

    return run_commit_finalizer(**kwargs)


def _success_result(instance_id: str) -> FinalizerInstanceResultWire:
    return FinalizerInstanceResultWire(
        instance_id=instance_id,
        status="success",
        attempts=[FinalizerAttemptWire(attempt=1, status="success")],
    )


def _failed_result(instance_id: str, message: str) -> FinalizerInstanceResultWire:
    return FinalizerInstanceResultWire(
        instance_id=instance_id,
        status="failed",
        attempts=[
            FinalizerAttemptWire(
                attempt=1,
                status="failed",
                diagnostic_code="controller_exception",
            )
        ],
        diagnostics=[
            FinalizerDiagnosticWire(
                code="controller_exception",
                severity="error",
                message=message,
                instance_id=instance_id,
            )
        ],
    )


def _write_aggregate_result(
    artifacts_dir: str | None,
    instance_results: list[FinalizerInstanceResultWire],
    status: str,
) -> None:
    payload = {
        "schema_version": 1,
        "status": status,
        "instances": [
            finalizer_wire_to_json_dict(result) for result in instance_results
        ],
        "diagnostics": [
            finalizer_wire_to_json_dict(diagnostic)
            for result in instance_results
            for diagnostic in result.diagnostics
        ],
    }
    write_finalizer_result(artifacts_dir, payload)


def _result_failure_message(result: FinalizerInstanceResultWire) -> str:
    if result.diagnostics:
        return result.diagnostics[0].message
    return f"finalizer {result.instance_id!r} failed"


__all__ = ["run_finalizers"]
