"""Diagnostics for AXE chops.

These checks back both ``sase axe chop doctor`` and the top-level
``sase doctor`` ``axe.chops`` check so the two surfaces never drift. They cover
configured script chops that cannot be resolved, executable chop scripts that
are installed but unconfigured, and the Telegram chop-script prerequisites.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sase.axe.chop_inventory import (
    ChopInventory,
    chop_inventory_to_dict,
    collect_chop_inventory,
)
from sase.diagnostics import CheckStatus

_TELEGRAM_ENV_VARS = ("SASE_TELEGRAM_BOT_CHAT_ID", "SASE_TELEGRAM_BOT_USERNAME")


@dataclass(frozen=True)
class ChopCheck:
    """One AXE chop diagnostic check."""

    id: str
    status: CheckStatus
    summary: str
    details: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()


@dataclass(frozen=True)
class ChopDoctorReport:
    """Complete AXE chop doctor report."""

    status: CheckStatus
    inventory: ChopInventory
    checks: tuple[ChopCheck, ...]


def build_chop_doctor_report(
    *,
    inventory: ChopInventory | None = None,
    which_fn: Callable[[str], str | None] = shutil.which,
) -> ChopDoctorReport:
    """Build a full doctor report for the configured and available chops."""
    chops = inventory or collect_chop_inventory()
    checks = build_chop_checks(chops, which_fn=which_fn)
    return ChopDoctorReport(
        status=aggregate_chop_status(checks),
        inventory=chops,
        checks=checks,
    )


def build_chop_checks(
    inventory: ChopInventory,
    *,
    which_fn: Callable[[str], str | None] = shutil.which,
) -> tuple[ChopCheck, ...]:
    """Build all chop diagnostic checks for the given inventory."""
    checks: list[ChopCheck] = []
    checks.extend(_configured_chop_checks(inventory))
    checks.extend(_unconfigured_chop_checks(inventory))
    checks.extend(_telegram_checks(inventory, which_fn=which_fn))
    return tuple(checks)


def aggregate_chop_status(checks: tuple[ChopCheck, ...]) -> CheckStatus:
    """Aggregate individual chop check statuses into an overall status."""
    statuses = {check.status for check in checks}
    if "ERROR" in statuses:
        return "ERROR"
    if "WARN" in statuses:
        return "WARN"
    if not statuses or statuses == {"SKIP"}:
        return "SKIP"
    return "OK"


def chop_check_to_dict(check: ChopCheck) -> dict[str, Any]:
    """Serialize a single chop check."""
    return {
        "id": check.id,
        "status": check.status,
        "summary": check.summary,
        "details": list(check.details),
        "next_steps": list(check.next_steps),
    }


def chop_doctor_report_to_dict(report: ChopDoctorReport) -> dict[str, Any]:
    """Serialize a chop doctor report to stable JSON-compatible primitives."""
    return {
        "schema_version": 1,
        "command": "doctor",
        "status": report.status,
        "chops": chop_inventory_to_dict(report.inventory),
        "checks": [chop_check_to_dict(check) for check in report.checks],
    }


def _configured_chop_checks(inventory: ChopInventory) -> tuple[ChopCheck, ...]:
    missing_chops = [
        chop for chop in inventory.configured_chops if chop.status == "missing"
    ]
    if not missing_chops:
        return (
            ChopCheck(
                id="configured_chop_scripts",
                status="OK",
                summary="All configured script chops resolve or are agent-backed.",
            ),
        )
    return tuple(
        ChopCheck(
            id=f"configured_chop:{chop.lumberjack}:{chop.name}",
            status="ERROR",
            summary=f"Configured script chop {chop.name} cannot be resolved.",
            details=(f"lumberjack={chop.lumberjack}",),
            next_steps=(
                "Install the package or script that provides this chop in the same environment, or update axe.lumberjacks.",
            ),
        )
        for chop in missing_chops
    )


def _unconfigured_chop_checks(inventory: ChopInventory) -> tuple[ChopCheck, ...]:
    unconfigured = inventory.available_unconfigured
    if not unconfigured:
        return ()
    names = ", ".join(script.name for script in unconfigured)
    return (
        ChopCheck(
            id="available_unconfigured_chops",
            status="WARN",
            summary="Executable chop scripts are installed but not configured.",
            details=(names,),
            next_steps=(
                "Add desired scripts under axe.lumberjacks in sase.yml; future chop enablement commands will manage this directly.",
            ),
        ),
    )


def _telegram_checks(
    inventory: ChopInventory,
    *,
    which_fn: Callable[[str], str | None],
) -> tuple[ChopCheck, ...]:
    if not _has_telegram_chop_scripts(inventory):
        return ()

    checks: list[ChopCheck] = []
    missing_env = tuple(name for name in _TELEGRAM_ENV_VARS if not os.environ.get(name))
    if missing_env:
        checks.append(
            ChopCheck(
                id="telegram_env",
                status="WARN",
                summary="Telegram chop scripts are installed, but required environment variables are missing.",
                details=missing_env,
                next_steps=(
                    "Set the missing SASE_TELEGRAM_* variables before enabling Telegram chops.",
                ),
            )
        )
    else:
        checks.append(
            ChopCheck(
                id="telegram_env",
                status="OK",
                summary="Required Telegram environment variables are set.",
            )
        )

    if which_fn("pass") is None:
        checks.append(
            ChopCheck(
                id="telegram_pass",
                status="WARN",
                summary="Telegram chop scripts are installed, but pass was not found.",
                next_steps=(
                    "Install pass and ensure `pass show telegram_sase_bot_token` works for the SASE process.",
                ),
            )
        )
    else:
        checks.append(
            ChopCheck(
                id="telegram_pass",
                status="OK",
                summary="pass is available for Telegram bot token lookup.",
            )
        )

    return tuple(checks)


def _has_telegram_chop_scripts(inventory: ChopInventory) -> bool:
    known_names = {"tg_inbound", "tg_outbound", "telegram_inbound", "telegram_outbound"}
    for script in inventory.available_scripts:
        if script.name in known_names or "telegram" in script.name:
            return True
    return False
