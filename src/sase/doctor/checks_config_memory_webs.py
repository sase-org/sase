"""Memory-web validation check for ``sase doctor``."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.diagnostics import CheckStatus, DiagnosticCheck
from sase.doctor.checks_config_common import MAX_DETAIL_ROWS
from sase.memory.web import (
    cross_scope_keyword_warnings,
    discover_memory_webs,
    validate_memory_webs,
)

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext


def check_config_memory_webs(context: DoctorContext) -> DiagnosticCheck:
    """Run memory-web discovery and validation without writing files."""

    project_discovery = discover_memory_webs(context.cwd)
    home_root = _home_root(context)
    home_discovery = (
        None
        if home_root.resolve(strict=False) == context.cwd.resolve(strict=False)
        else discover_memory_webs(home_root)
    )

    project_report = validate_memory_webs(project_discovery)
    home_report = (
        None if home_discovery is None else validate_memory_webs(home_discovery)
    )
    blockers = [
        *_prefixed("project", project_report.blockers),
        *(() if home_report is None else _prefixed("home", home_report.blockers)),
    ]
    warnings = [
        *_prefixed("project", project_report.warnings),
        *(() if home_report is None else _prefixed("home", home_report.warnings)),
    ]
    if (
        home_report is not None
        and not project_report.blockers
        and not home_report.blockers
    ):
        warnings.extend(
            cross_scope_keyword_warnings(
                project_webs=project_discovery.webs,
                home_webs=home_discovery.webs if home_discovery is not None else (),
            )
        )

    status: CheckStatus = "ERROR" if blockers else "WARN" if warnings else "OK"
    return DiagnosticCheck(
        id="config.memory_webs",
        group="config",
        status=status,
        title="Memory webs",
        summary=_summary(
            project_webs=len(project_discovery.webs),
            home_webs=0 if home_discovery is None else len(home_discovery.webs),
            blockers=len(blockers),
            warnings=len(warnings),
        ),
        details=tuple((*blockers, *warnings)[:MAX_DETAIL_ROWS]),
        next_steps=(
            ("Fix memory web descriptors/strands, then rerun `sase doctor`.",)
            if blockers or warnings
            else ()
        ),
        data={
            "project": _discovery_data(project_discovery),
            "home": None if home_discovery is None else _discovery_data(home_discovery),
            "blocker_count": len(blockers),
            "warning_count": len(warnings),
        },
    )


def _home_root(context: DoctorContext) -> Path:
    raw_home = context.env.get("HOME")
    return Path(raw_home).expanduser() if raw_home else Path.home()


def _prefixed(scope: str, messages: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(f"{scope}: {message}" for message in messages)


def _summary(
    *,
    project_webs: int,
    home_webs: int,
    blockers: int,
    warnings: int,
) -> str:
    if blockers:
        return f"{blockers} memory web blocker(s), {warnings} warning(s)"
    if warnings:
        return f"{warnings} memory web warning(s)"
    return f"memory webs are valid: {project_webs} project, {home_webs} home"


def _discovery_data(discovery: Any) -> dict[str, Any]:
    return {
        "root": str(discovery.root),
        "memory_root": None
        if discovery.memory_root is None
        else str(discovery.memory_root),
        "webs": [web.slug for web in discovery.webs],
        "issues": [
            {"code": issue.code, "path": str(issue.path), "message": issue.message}
            for issue in discovery.issues
        ],
    }


__all__ = ["check_config_memory_webs"]
