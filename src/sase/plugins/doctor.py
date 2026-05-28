"""Doctor checks for ``sase plugin``."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from sase.plugins.chops import ChopInventory, collect_chop_inventory
from sase.plugins.inventory import PluginInventory, collect_plugin_inventory

CheckStatus = Literal["OK", "WARN", "ERROR", "SKIP"]


@dataclass(frozen=True)
class DoctorCheck:
    """One plugin diagnostic check."""

    id: str
    status: CheckStatus
    summary: str
    details: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()


@dataclass(frozen=True)
class DoctorReport:
    """Complete plugin doctor report."""

    status: CheckStatus
    plugin_inventory: PluginInventory
    chop_inventory: ChopInventory
    checks: tuple[DoctorCheck, ...]


def build_plugin_doctor_report(
    *,
    plugin_inventory: PluginInventory | None = None,
    chop_inventory: ChopInventory | None = None,
    which_fn: Callable[[str], str | None] = shutil.which,
    run_fn: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> DoctorReport:
    """Build a full doctor report for the current SASE plugin environment."""
    plugins = plugin_inventory or collect_plugin_inventory()
    chops = chop_inventory or collect_chop_inventory()
    checks = list(build_inventory_checks(plugins, chops))
    checks.extend(_github_checks(plugins, which_fn=which_fn, run_fn=run_fn))
    checks.extend(_telegram_checks(chops, which_fn=which_fn))
    return DoctorReport(
        status=aggregate_check_status(tuple(checks)),
        plugin_inventory=plugins,
        chop_inventory=chops,
        checks=tuple(checks),
    )


def build_inventory_checks(
    plugin_inventory: PluginInventory,
    chop_inventory: ChopInventory,
) -> tuple[DoctorCheck, ...]:
    """Build checks that require only inventory data and no external probes."""
    checks: list[DoctorCheck] = []

    if plugin_inventory.disabled_env:
        checks.append(
            DoctorCheck(
                id="plugin_resource_loading_disabled",
                status="WARN",
                summary="Plugin resource loading is disabled by environment variables.",
                details=plugin_inventory.disabled_env,
                next_steps=(
                    "Unset the listed variables before starting SASE if plugin configs or xprompts should load.",
                ),
            )
        )

    resource_errors = [
        ep for ep in plugin_inventory.resource_entry_points if ep.load_status == "error"
    ]
    if resource_errors:
        for ep in resource_errors:
            checks.append(
                DoctorCheck(
                    id=f"resource_entry_point:{ep.group}:{ep.name}",
                    status="ERROR",
                    summary=f"Resource entry point {ep.group}:{ep.name} failed to load.",
                    details=(
                        f"package={ep.package} version={ep.version}",
                        ep.load_error or "unknown load error",
                    ),
                    next_steps=(
                        f"Reinstall or upgrade {ep.package} in the same environment as this sase executable.",
                    ),
                )
            )
    else:
        checks.append(
            DoctorCheck(
                id="resource_entry_points",
                status="OK",
                summary="No resource entry point load failures were found.",
            )
        )

    missing_chops = [
        chop for chop in chop_inventory.configured_chops if chop.status == "missing"
    ]
    if missing_chops:
        for chop in missing_chops:
            checks.append(
                DoctorCheck(
                    id=f"configured_chop:{chop.lumberjack}:{chop.name}",
                    status="ERROR",
                    summary=f"Configured script chop {chop.name} cannot be resolved.",
                    details=(f"lumberjack={chop.lumberjack}",),
                    next_steps=(
                        "Install the package or script that provides this chop in the same environment, or update axe.lumberjacks.",
                    ),
                )
            )
    else:
        checks.append(
            DoctorCheck(
                id="configured_chop_scripts",
                status="OK",
                summary="All configured script chops resolve or are agent-backed.",
            )
        )

    unconfigured = chop_inventory.available_unconfigured
    if unconfigured:
        names = ", ".join(script.name for script in unconfigured)
        checks.append(
            DoctorCheck(
                id="available_unconfigured_chops",
                status="WARN",
                summary="Executable chop scripts are installed but not configured.",
                details=(names,),
                next_steps=(
                    "Add desired scripts under axe.lumberjacks in sase.yml; future chop enablement commands will manage this directly.",
                ),
            )
        )

    return tuple(checks)


def aggregate_check_status(checks: tuple[DoctorCheck, ...]) -> CheckStatus:
    """Aggregate individual check statuses into an overall status."""
    statuses = {check.status for check in checks}
    if "ERROR" in statuses:
        return "ERROR"
    if "WARN" in statuses:
        return "WARN"
    if statuses == {"SKIP"}:
        return "SKIP"
    return "OK"


def doctor_report_to_dict(report: DoctorReport) -> dict[str, Any]:
    """Serialize a doctor report to stable JSON-compatible primitives."""
    from sase.plugins.chops import chop_inventory_to_dict
    from sase.plugins.inventory import plugin_inventory_to_dict

    return {
        "schema_version": 1,
        "command": "doctor",
        "status": report.status,
        "plugins": plugin_inventory_to_dict(report.plugin_inventory),
        "chops": chop_inventory_to_dict(report.chop_inventory),
        "checks": [doctor_check_to_dict(check) for check in report.checks],
    }


def doctor_check_to_dict(check: DoctorCheck) -> dict[str, Any]:
    """Serialize a single doctor check."""
    return {
        "id": check.id,
        "status": check.status,
        "summary": check.summary,
        "details": list(check.details),
        "next_steps": list(check.next_steps),
    }


def _github_checks(
    plugin_inventory: PluginInventory,
    *,
    which_fn: Callable[[str], str | None],
    run_fn: Callable[..., subprocess.CompletedProcess[str]],
) -> tuple[DoctorCheck, ...]:
    if not _has_github_plugin(plugin_inventory):
        return ()

    gh_path = which_fn("gh")
    if gh_path is None:
        return (
            DoctorCheck(
                id="github_cli",
                status="WARN",
                summary="A GitHub SASE plugin is installed, but the gh CLI was not found.",
                next_steps=(
                    "Install GitHub CLI and run `gh auth login` if this plugin should create or update PRs.",
                ),
            ),
        )

    try:
        result = run_fn(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return (
            DoctorCheck(
                id="github_auth",
                status="WARN",
                summary="GitHub CLI is installed, but gh auth status could not be checked.",
                details=(f"{type(exc).__name__}: {exc}",),
                next_steps=(
                    "Run `gh auth status` manually before relying on GitHub plugin operations.",
                ),
            ),
        )

    if result.returncode != 0:
        detail = _first_nonempty_line(result.stderr, result.stdout)
        details = (detail,) if detail else ()
        return (
            DoctorCheck(
                id="github_auth",
                status="WARN",
                summary="GitHub CLI is installed, but gh auth status did not pass.",
                details=details,
                next_steps=(
                    "Run `gh auth login` or fix the account reported by `gh auth status`.",
                ),
            ),
        )

    return (
        DoctorCheck(
            id="github_auth",
            status="OK",
            summary="GitHub CLI is installed and authenticated.",
            details=(gh_path,),
        ),
    )


def _telegram_checks(
    chop_inventory: ChopInventory,
    *,
    which_fn: Callable[[str], str | None],
) -> tuple[DoctorCheck, ...]:
    if not _has_telegram_chop_scripts(chop_inventory):
        return ()

    checks: list[DoctorCheck] = []
    required_env = ("SASE_TELEGRAM_BOT_CHAT_ID", "SASE_TELEGRAM_BOT_USERNAME")
    missing_env = tuple(name for name in required_env if not os.environ.get(name))
    if missing_env:
        checks.append(
            DoctorCheck(
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
            DoctorCheck(
                id="telegram_env",
                status="OK",
                summary="Required Telegram environment variables are set.",
            )
        )

    if which_fn("pass") is None:
        checks.append(
            DoctorCheck(
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
            DoctorCheck(
                id="telegram_pass",
                status="OK",
                summary="pass is available for Telegram bot token lookup.",
            )
        )

    return tuple(checks)


def _has_github_plugin(plugin_inventory: PluginInventory) -> bool:
    for ep in plugin_inventory.entry_points:
        package = ep.package.lower()
        if package == "sase-github":
            return True
        if ep.name == "github" and ep.group in {"sase_vcs", "sase_workspace"}:
            return True
    return False


def _has_telegram_chop_scripts(chop_inventory: ChopInventory) -> bool:
    known_names = {"tg_inbound", "tg_outbound", "telegram_inbound", "telegram_outbound"}
    for script in chop_inventory.available_scripts:
        if script.name in known_names or "telegram" in script.name:
            return True
    return False


def _first_nonempty_line(*texts: str) -> str | None:
    for text in texts:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
    return None
