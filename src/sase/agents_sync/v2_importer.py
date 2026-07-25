"""Transactional local-history import for validated v2 agent hoods."""

from __future__ import annotations

from sase.agents_sync.models import IntegrationCounts, ProjectTarget
from sase.agents_sync.v2_import_package import ValidatedV2HoodPackage
from sase.agents_sync.v2_import_planning import (
    ImportPreflightContext,
    build_import_preflight_context,
    preflight_hood,
)
from sase.agents_sync.v2_import_storage import (
    journal_path,
    project_import_lock,
    transaction_is_complete,
    transaction_key_is_valid,
)
from sase.agents_sync.v2_import_transactions import (
    apply_and_finalize_transaction,
    prepare_transaction,
    recover_v2_import_transactions,
)
from sase.core.agent_identity_facade import AgentIdentitySnapshot


def integrate_v2_hoods(
    target: ProjectTarget,
    packages: tuple[ValidatedV2HoodPackage, ...],
    *,
    identity: AgentIdentitySnapshot,
    preflight_context: ImportPreflightContext | None = None,
) -> IntegrationCounts:
    """Preflight and import independently validated hoods one transaction each."""

    diagnostics: list[str] = []
    imported = refreshed = unchanged = quarantined = 0
    families = runs = 0
    context = preflight_context or (
        build_import_preflight_context(target, identity, packages) if packages else None
    )
    if context is None or not context.recovery_complete:
        with project_import_lock(target.project_key):
            diagnostics.extend(
                recover_v2_import_transactions(target, identity=identity)
            )
        if context is not None:
            context.recovery_complete = True

    for package in packages:
        label = f"{package.owner.username}.{package.owner.machine_name}.{package.hood}"
        try:
            plan = preflight_hood(
                target,
                package,
                identity,
                context=context,
            )
            if not plan.changed_runs or (
                plan.is_unchanged
                and transaction_is_complete(
                    target.project_key,
                    plan.transaction_key,
                )
            ):
                unchanged += 1
                continue
            prepare_transaction(target, plan)
            with project_import_lock(target.project_key):
                apply_and_finalize_transaction(
                    target,
                    journal_path(target.project_key, plan.transaction_key),
                    identity,
                )
            if plan.is_refresh:
                refreshed += 1
            else:
                imported += 1
            families += sum(
                container.record.kind == "family" for container in plan.containers
            )
            runs += len(plan.changed_runs)
        except Exception as exc:  # noqa: BLE001 - hood-scoped quarantine contract
            quarantined += 1
            diagnostics.append(f"{label}: quarantined v2 import: {exc}")
    return IntegrationCounts(
        hoods_imported=imported,
        hoods_refreshed=refreshed,
        hoods_unchanged=unchanged,
        hoods_quarantined=quarantined,
        families_imported=families,
        runs_imported=runs,
        diagnostics=tuple(diagnostics),
    )


def import_transaction_is_complete(
    project_key: str,
    transaction_key: str,
) -> bool:
    """Return whether a loader-visible imported transaction is complete."""

    if not transaction_key_is_valid(transaction_key):
        return False
    return transaction_is_complete(project_key, transaction_key)


__all__ = [
    "import_transaction_is_complete",
    "integrate_v2_hoods",
]
