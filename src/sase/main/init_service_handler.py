"""Machine-scoped service-platform step for ``sase init`` onboarding."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from sase.feature_flags import FeatureFlag, current_flags
from sase.main.init_plan import InitAction, InitPlan
from sase.service.env import render_service_environment
from sase.service.platform import (
    DECLINED_MARKER,
    ServicePlatformPlan,
    apply_service_init,
    service_init_plan,
)
from sase.service.state import read_service_state, set_service_marker


def plan_init_service(args: argparse.Namespace) -> InitPlan:
    """Return a read-only plan for optional service-platform installation."""
    if not current_flags().enabled(FeatureFlag.service_host):
        return InitPlan(
            command="service",
            label="Service",
            summary="service host platform unit is inactive while service_host is disabled",
            actions=(),
        )
    if _declined_for_bare_onboarding(args):
        return InitPlan(
            command="service",
            label="Service",
            summary="service host platform unit was previously declined on this machine",
            actions=(),
        )
    plan = service_init_plan(force=bool(getattr(args, "force", False)))
    return _init_plan_from_platform(plan)


def run_init_service(args: argparse.Namespace) -> int:
    """Apply service-platform installation for ``sase init service``."""
    if getattr(args, "check", False):
        from .init_onboarding import run_init_check
        from .init_registry import InitCommandSpec

        return run_init_check(
            args,
            specs=(
                InitCommandSpec(
                    name="service",
                    label="Service",
                    plan=plan_init_service,
                    run=run_init_service,
                    scope="machine",
                    decline=decline_init_service,
                ),
            ),
        )
    result = apply_service_init(force=bool(getattr(args, "force", False)))
    if not result.ok:
        print(result.message, file=sys.stderr)
        for blocker in result.plan.blockers if result.plan is not None else ():
            print(f"- {blocker}", file=sys.stderr)
        return 1
    print(result.message)
    return 0


def handle_init_service_command(args: argparse.Namespace) -> None:
    """Compatibility wrapper for ``sase init service``."""
    sys.exit(run_init_service(args))


def decline_init_service(_args: argparse.Namespace) -> None:
    """Persist an interactive onboarding decline for the service step."""
    set_service_marker(
        DECLINED_MARKER,
        "init",
        detail="interactive decline",
    )


def _init_plan_from_platform(plan: ServicePlatformPlan) -> InitPlan:
    actions: list[InitAction] = []
    for action in plan.actions:
        if str(plan.definition.definition_path) in action:
            actions.append(
                InitAction(
                    path=plan.definition.definition_path,
                    operation="update"
                    if plan.inspection and plan.inspection.definition_exists
                    else "create",
                    detail="native service host unit",
                    new_content=plan.definition.content,
                )
            )
        elif str(plan.definition.env_path) in action:
            actions.append(
                InitAction(
                    path=plan.definition.env_path,
                    operation="update"
                    if plan.inspection and plan.inspection.environment_exists
                    else "create",
                    detail="captured service environment (values redacted)",
                    new_content=render_service_environment(plan.captured_env_redacted),
                )
            )
        else:
            actions.append(
                InitAction(
                    path=Path(plan.definition.identity),
                    operation="validate",
                    detail=action,
                )
            )
    summary = {
        "current": "service host platform unit is current",
        "needs_attention": "service host platform unit needs installation or readiness attention",
        "blocked": "service host platform unit installation is blocked",
    }[plan.status]
    return InitPlan(
        command="service",
        label="Service",
        summary=summary,
        actions=tuple(actions),
        warnings=plan.warnings,
        blockers=plan.blockers,
    )


def _declined_for_bare_onboarding(args: argparse.Namespace) -> bool:
    if getattr(args, "init_subcommand", None) == "service":
        return False
    try:
        marker = read_service_state().state.markers.get(DECLINED_MARKER)
    except Exception:
        return False
    return marker is not None


__all__ = [
    "decline_init_service",
    "handle_init_service_command",
    "plan_init_service",
    "run_init_service",
]
