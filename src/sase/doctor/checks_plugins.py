"""Plugin subsystem checks for ``sase doctor``.

Resource entry-point loading and provider (GitHub CLI) prerequisites are support
diagnostics, so they live under ``sase doctor`` rather than any plugin command.
Chop diagnostics live separately under ``axe.chops`` (see ``checks_axe``).
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from typing import TYPE_CHECKING

from sase.diagnostics import CheckSpec, CheckStatus, DiagnosticCheck
from sase.plugins.inventory import (
    PluginInventory,
    collect_plugin_inventory,
)
from sase.plugins.required import (
    RequiredPluginsReport,
    load_project_required_plugins_config,
    resolve_required_plugins,
)

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_MAX_DETAIL_ROWS = 10


def plugin_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return default plugin check specs."""
    return (
        CheckSpec(
            id="plugins.required",
            group="plugins",
            title="Required plugins",
            runner=lambda: _check_plugins_required(context),
        ),
        CheckSpec(
            id="plugins.resources",
            group="plugins",
            title="Resource plugin loading",
            runner=_check_plugins_resources,
        ),
        CheckSpec(
            id="plugins.github",
            group="plugins",
            title="GitHub plugin prerequisites",
            runner=_check_plugins_github,
        ),
    )


def _check_plugins_required(context: DoctorContext) -> DiagnosticCheck:
    """Report missing, mismatched, or undeclared ``plugins.required`` entries."""
    config, config_path, load_error = load_project_required_plugins_config(context.cwd)
    if load_error is not None:
        return DiagnosticCheck(
            id="plugins.required",
            group="plugins",
            status="ERROR",
            title="Required plugins",
            summary="project config could not be read for plugins.required",
            details=(load_error,),
            next_steps=(
                "Fix the project sase.yml parse error, then rerun `sase doctor`.",
            ),
            data={
                "status": "ERROR",
                "config_path": str(config_path) if config_path is not None else None,
                "load_error": load_error,
            },
        )
    if config is None:
        return DiagnosticCheck(
            id="plugins.required",
            group="plugins",
            status="SKIP",
            title="Required plugins",
            summary="no project config in this checkout",
            data={"status": "SKIP", "config_path": None},
        )

    report = resolve_required_plugins(config)
    return _required_plugins_check_from_report(
        report,
        config_path=str(config_path) if config_path is not None else None,
    )


def _required_plugins_check_from_report(
    report: RequiredPluginsReport,
    *,
    config_path: str | None,
) -> DiagnosticCheck:
    if report.ok:
        declared = len(report.requirements)
        summary = (
            f"{declared} required plugin(s) satisfied"
            if declared
            else "no required plugins declared"
        )
        return DiagnosticCheck(
            id="plugins.required",
            group="plugins",
            status="OK",
            title="Required plugins",
            summary=summary,
            data={
                "status": "OK",
                "config_path": config_path,
                "required_count": declared,
                "satisfied_count": len(report.satisfied),
                "issue_count": 0,
            },
        )

    details = tuple(issue.message for issue in report.issues[:_MAX_DETAIL_ROWS])
    next_steps = tuple(
        dict.fromkeys(
            issue.install_command
            for issue in report.issues
            if issue.install_command is not None
        )
    )[:_MAX_DETAIL_ROWS]
    return DiagnosticCheck(
        id="plugins.required",
        group="plugins",
        status="ERROR",
        title="Required plugins",
        summary=f"{len(report.issues)} plugins.required problem(s) found",
        details=details,
        next_steps=next_steps,
        data={
            "status": "ERROR",
            "config_path": config_path,
            "required_count": len(report.requirements),
            "satisfied_count": len(report.satisfied),
            "issue_count": len(report.issues),
            "issues": [
                {
                    "kind": issue.kind,
                    "message": issue.message,
                    "name": issue.name,
                    "requirement": issue.requirement,
                    "config_path": issue.config_path,
                    "install_command": issue.install_command,
                }
                for issue in report.issues[:_MAX_DETAIL_ROWS]
            ],
        },
    )


def _check_plugins_resources() -> DiagnosticCheck:
    """Report resource entry-point load failures and disabled resource loading."""
    inventory = collect_plugin_inventory()
    resource_errors = tuple(
        ep for ep in inventory.resource_entry_points if ep.load_status == "error"
    )
    disabled_env = inventory.disabled_env

    status: CheckStatus
    if resource_errors:
        status = "ERROR"
        summary = f"{len(resource_errors)} resource entry point(s) failed to load"
        details = tuple(
            f"{ep.group}:{ep.name} ({ep.package} {ep.version}): "
            f"{ep.load_error or 'unknown load error'}"
            for ep in resource_errors[:_MAX_DETAIL_ROWS]
        )
        next_steps = tuple(
            dict.fromkeys(
                f"Reinstall or upgrade {ep.package} in the same environment as this sase executable."
                for ep in resource_errors
            )
        )[:_MAX_DETAIL_ROWS]
    elif disabled_env:
        status = "WARN"
        summary = "Resource plugin loading is disabled by environment variables."
        details = disabled_env
        next_steps = (
            "Unset the listed variables before starting SASE if plugin configs or xprompts should load.",
        )
    else:
        status = "OK"
        summary = (
            f"no resource entry point load failures "
            f"({len(inventory.resource_entry_points)} resource entry point(s))"
        )
        details = ()
        next_steps = ()

    return DiagnosticCheck(
        id="plugins.resources",
        group="plugins",
        status=status,
        title="Resource plugin loading",
        summary=summary,
        details=details,
        next_steps=next_steps,
        data={
            "status": status,
            "resource_entry_point_count": len(inventory.resource_entry_points),
            "resource_error_count": len(resource_errors),
            "disabled_env": list(disabled_env),
            "resource_errors": [
                {
                    "group": ep.group,
                    "name": ep.name,
                    "package": ep.package,
                    "version": ep.version,
                    "load_error": ep.load_error,
                }
                for ep in resource_errors[:_MAX_DETAIL_ROWS]
            ],
        },
    )


def _check_plugins_github(
    *,
    which_fn: Callable[[str], str | None] = shutil.which,
    run_fn: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[DiagnosticCheck, ...]:
    """Probe the GitHub CLI when a GitHub provider plugin is installed."""
    inventory = collect_plugin_inventory(load_resource_entry_points=False)
    if not _has_github_plugin(inventory):
        return ()

    gh_path = which_fn("gh")
    if gh_path is None:
        return (
            DiagnosticCheck(
                id="plugins.github",
                group="plugins",
                status="WARN",
                title="GitHub plugin prerequisites",
                summary="GitHub plugin is installed, but the gh CLI was not found",
                next_steps=(
                    "Install GitHub CLI and run `gh auth login` if this plugin should create or update PRs.",
                ),
                data={"gh_installed": False, "gh_authenticated": False},
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
            DiagnosticCheck(
                id="plugins.github",
                group="plugins",
                status="WARN",
                title="GitHub plugin prerequisites",
                summary="gh CLI is installed, but gh auth status could not be checked",
                details=(f"{type(exc).__name__}: {exc}",),
                next_steps=(
                    "Run `gh auth status` manually before relying on GitHub plugin operations.",
                ),
                data={
                    "gh_installed": True,
                    "gh_authenticated": False,
                    "gh_path": gh_path,
                },
            ),
        )

    if result.returncode != 0:
        detail = _first_nonempty_line(result.stderr, result.stdout)
        return (
            DiagnosticCheck(
                id="plugins.github",
                group="plugins",
                status="WARN",
                title="GitHub plugin prerequisites",
                summary="gh CLI is installed, but gh auth status did not pass",
                details=(detail,) if detail else (),
                next_steps=(
                    "Run `gh auth login` or fix the account reported by `gh auth status`.",
                ),
                data={
                    "gh_installed": True,
                    "gh_authenticated": False,
                    "gh_path": gh_path,
                },
            ),
        )

    return (
        DiagnosticCheck(
            id="plugins.github",
            group="plugins",
            status="OK",
            title="GitHub plugin prerequisites",
            summary="gh CLI is installed and authenticated",
            details=(gh_path,),
            data={"gh_installed": True, "gh_authenticated": True, "gh_path": gh_path},
        ),
    )


def _has_github_plugin(inventory: PluginInventory) -> bool:
    for ep in inventory.entry_points:
        if ep.package.lower() == "sase-github":
            return True
        if ep.name == "github" and ep.group in {"sase_vcs", "sase_workspace"}:
            return True
    return False


def _first_nonempty_line(*texts: str) -> str | None:
    for text in texts:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
    return None


__all__ = [
    "plugin_check_specs",
]
