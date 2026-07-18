"""Diagnostics for AXE chops.

These checks back both ``sase axe chop doctor`` and the top-level
``sase doctor`` ``axe.chops`` check so the two surfaces never drift. They cover
configured script chops that cannot be resolved, executable chop scripts that
are installed but unconfigured, and the Telegram chop-script prerequisites.
"""

from __future__ import annotations

import os
import shutil
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.axe.chop_inventory import (
    ChopInventory,
    ConfiguredChopRecord,
    chop_inventory_to_dict,
    collect_chop_inventory,
)
from sase.axe.config import AxeConfig, AxeConfigError
from sase.diagnostics import CheckStatus

_TELEGRAM_ENV_VARS = ("SASE_TELEGRAM_BOT_CHAT_ID", "SASE_TELEGRAM_BOT_USERNAME")
_TELEGRAM_BOT_TOKEN_ENV_VAR = "SASE_TELEGRAM_BOT_TOKEN"
_TELEGRAM_BOT_TOKEN_FILE = Path(".sase") / "telegram_bot_token"
_TELEGRAM_CHOP_NAMES = {
    "tg_inbound",
    "tg_outbound",
    "telegram_inbound",
    "telegram_outbound",
}
_TELEGRAM_TOKEN_NEXT_STEP = (
    "Set SASE_TELEGRAM_BOT_TOKEN in process or per-chop env, create "
    "~/.sase/telegram_bot_token with mode 600, or install pass and ensure "
    "`pass show telegram_sase_bot_token` works."
)


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
    config_checks: tuple[ChopCheck, ...] = ()
    if inventory is None:
        try:
            chops = collect_chop_inventory()
        except AxeConfigError as exc:
            # Doctor must remain usable when config loading itself fails.
            chops = collect_chop_inventory(AxeConfig())
            config_checks = tuple(
                ChopCheck(
                    id=f"axe_config:{diagnostic.code}:{index}",
                    status="ERROR",
                    summary="Invalid axe configuration.",
                    details=(diagnostic.format(),),
                    next_steps=(
                        "Fix the reported axe config field in its source layer and rerun `sase axe chop doctor`.",
                    ),
                )
                for index, diagnostic in enumerate(exc.diagnostics)
            )
    else:
        chops = inventory
    checks = (*config_checks, *_build_chop_checks(chops, which_fn=which_fn))
    return ChopDoctorReport(
        status=_aggregate_chop_status(checks),
        inventory=chops,
        checks=checks,
    )


def _build_chop_checks(
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


def _aggregate_chop_status(checks: tuple[ChopCheck, ...]) -> CheckStatus:
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
                summary="All configured chop scripts resolve.",
            ),
        )
    return tuple(
        ChopCheck(
            id=f"configured_chop:{chop.lumberjack}:{chop.name}",
            status="ERROR",
            summary=f"Configured chop script {chop.script} cannot be resolved.",
            details=(
                f"lumberjack={chop.lumberjack}",
                f"chop={chop.name}",
                f"script={chop.script}",
            ),
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
    missing_env = tuple(
        name for name in _TELEGRAM_ENV_VARS if not _telegram_env_is_set(inventory, name)
    )
    if missing_env:
        checks.append(
            ChopCheck(
                id="telegram_env",
                status="WARN",
                summary="Telegram chop scripts are installed or configured, but required environment variables are missing.",
                details=missing_env,
                next_steps=(
                    "Set the missing SASE_TELEGRAM_* variables in process env or per-chop env before enabling Telegram chops.",
                ),
            )
        )
    else:
        checks.append(
            ChopCheck(
                id="telegram_env",
                status="OK",
                summary="Required Telegram environment variables are set or configured per chop.",
            )
        )

    token_source, token_details = _telegram_token_source(
        inventory,
        which_fn=which_fn,
    )
    if token_source is None:
        telegram_enabled = _telegram_is_enabled()
        configured_chops = _configured_telegram_chops(inventory)
        is_outage = telegram_enabled and bool(configured_chops)
        status: CheckStatus = "ERROR" if is_outage else "WARN"
        summary = (
            "Telegram is enabled and configured, but no Telegram bot token source is available."
            if is_outage
            else "Telegram chop scripts are installed or configured, but no Telegram bot token source is available."
        )
        checks.append(
            ChopCheck(
                id="telegram_bot_token",
                status=status,
                summary=summary,
                details=(
                    *token_details,
                    f"telegram_enabled={telegram_enabled}",
                    f"configured_telegram_chops={_chop_names(configured_chops)}",
                ),
                next_steps=(_TELEGRAM_TOKEN_NEXT_STEP,),
            )
        )
    else:
        checks.append(
            ChopCheck(
                id="telegram_bot_token",
                status="OK",
                summary=f"Telegram bot token source is available ({token_source}).",
                details=token_details,
            )
        )

    return tuple(checks)


def _has_telegram_chop_scripts(inventory: ChopInventory) -> bool:
    if _configured_telegram_chops(inventory):
        return True
    for script in inventory.available_scripts:
        if _is_telegram_chop_name(script.name):
            return True
    return False


def _configured_telegram_chops(
    inventory: ChopInventory,
) -> tuple[ConfiguredChopRecord, ...]:
    return tuple(
        chop
        for chop in inventory.configured_chops
        if _is_telegram_chop_name(chop.name) or _is_telegram_chop_name(chop.script)
    )


def _is_telegram_chop_name(name: str) -> bool:
    normalized = name.removeprefix("sase_chop_")
    return normalized in _TELEGRAM_CHOP_NAMES or "telegram" in normalized


def _telegram_env_is_set(inventory: ChopInventory, name: str) -> bool:
    if os.environ.get(name, "").strip():
        return True
    return any(
        chop.env.get(name, "").strip() for chop in _configured_telegram_chops(inventory)
    )


def _telegram_token_source(
    inventory: ChopInventory,
    *,
    which_fn: Callable[[str], str | None],
) -> tuple[str | None, tuple[str, ...]]:
    if _telegram_env_is_set(inventory, _TELEGRAM_BOT_TOKEN_ENV_VAR):
        return (_TELEGRAM_BOT_TOKEN_ENV_VAR, ())

    file_available, file_detail = _telegram_token_file_status()
    if file_available:
        return ("~/.sase/telegram_bot_token", (file_detail,))

    if which_fn("pass") is not None:
        return ("pass", ("pass executable was found",))

    return (None, (file_detail, "pass executable was not found"))


def _telegram_token_file_status() -> tuple[bool, str]:
    token_path = Path.home() / _TELEGRAM_BOT_TOKEN_FILE
    display_path = "~/.sase/telegram_bot_token"
    try:
        token_stat = token_path.stat()
    except FileNotFoundError:
        return (False, f"{display_path} does not exist")
    except OSError as exc:
        return (False, f"{display_path} could not be inspected: {exc}")

    if not stat.S_ISREG(token_stat.st_mode):
        return (False, f"{display_path} is not a regular file")
    if token_stat.st_mode & (stat.S_IRGRP | stat.S_IROTH):
        return (False, f"{display_path} is group/other-readable; run chmod 600")

    try:
        token = token_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return (False, f"{display_path} could not be read: {exc}")
    if not token:
        return (False, f"{display_path} is empty")
    return (True, f"{display_path} exists with restricted permissions")


def _telegram_is_enabled() -> bool:
    try:
        return (Path.home() / ".sase" / "telegram_is_enabled").exists()
    except OSError:
        return False


def _chop_names(chops: tuple[ConfiguredChopRecord, ...]) -> str:
    return ", ".join(chop.name for chop in chops) or "-"
