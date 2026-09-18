"""Service-platform readiness checks for ``sase doctor``."""

from __future__ import annotations

from sase.diagnostics import DiagnosticCheck
from sase.feature_flags import FeatureFlag, current_flags
from sase.service.platform import service_init_plan


def check_service_platform() -> DiagnosticCheck:
    """Report native service-host installation readiness."""
    if not current_flags().enabled(FeatureFlag.service_host):
        return DiagnosticCheck(
            id="service.platform",
            group="service",
            status="SKIP",
            title="Service platform unit",
            summary="service_host beta flag is disabled",
            next_steps=(
                "Enable `service_host` and rerun `sase doctor -C service.platform`.",
            ),
        )
    plan = service_init_plan(force=True)
    if plan.blockers:
        return DiagnosticCheck(
            id="service.platform",
            group="service",
            status="ERROR",
            title="Service platform unit",
            summary="service platform unit cannot be installed safely",
            details=plan.blockers,
            next_steps=("Run `sase service init --check` for the full platform plan.",),
            data={"unit": plan.definition.identity},
        )
    if plan.actions or plan.warnings:
        return DiagnosticCheck(
            id="service.platform",
            group="service",
            status="WARN",
            title="Service platform unit",
            summary="service platform unit needs attention",
            details=(*plan.actions, *plan.warnings),
            next_steps=(
                "Run `sase service init --diff`, then `sase service init --yes`.",
            ),
            data={"unit": plan.definition.identity},
        )
    return DiagnosticCheck(
        id="service.platform",
        group="service",
        status="OK",
        title="Service platform unit",
        summary=f"{plan.definition.identity} is current",
        data={"unit": plan.definition.identity},
    )


__all__ = ["check_service_platform"]
