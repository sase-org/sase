"""Deep VCS pull-request checks for ``sase doctor``."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from sase.axe.chop_script_runner import compose_chop_subprocess_env
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.diagnostics import CheckStatus, DiagnosticCheck
from sase.project_display_names import project_display_name_for
from sase.vcs_provider import get_vcs_provider, supports_pull_requests

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext


def check_vcs_pull_requests(context: DoctorContext) -> DiagnosticCheck:
    """Probe PR listing for enabled projects using the detached chop env."""

    try:
        records = [
            record
            for record in list_project_records(sase_projects_dir(), "enabled")
            if record.is_project and record.workspace_dir
        ]
    except Exception as exc:  # noqa: BLE001 - doctor reports facade failures.
        return DiagnosticCheck(
            id="vcs.pull_requests",
            group="vcs",
            status="ERROR",
            title="VCS pull requests",
            summary="enabled project records could not be loaded",
            details=(f"{type(exc).__name__}: {exc}",),
        )

    if not records:
        return DiagnosticCheck(
            id="vcs.pull_requests",
            group="vcs",
            status="SKIP",
            title="VCS pull requests",
            summary="no enabled projects with workspace dirs were found",
        )

    rows: list[dict[str, object]] = []
    env = compose_chop_subprocess_env(context.env)
    with _temporary_environ(env):
        for record in records:
            rows.append(
                _probe_project(
                    project_display_name_for(record.project_name),
                    record.workspace_dir or "",
                )
            )

    probed = [row for row in rows if row["status"] != "skipped"]
    failed = [row for row in probed if row["status"] != "ok"]
    if not probed:
        return DiagnosticCheck(
            id="vcs.pull_requests",
            group="vcs",
            status="SKIP",
            title="VCS pull requests",
            summary="no enabled project supports pull-request listing",
            data={"projects": rows},
        )

    status: CheckStatus = "ERROR" if failed else "OK"
    ok_count = sum(1 for row in probed if row["status"] == "ok")
    return DiagnosticCheck(
        id="vcs.pull_requests",
        group="vcs",
        status=status,
        title="VCS pull requests",
        summary=f"{ok_count}/{len(probed)} PR listing probe(s) succeeded",
        details=tuple(f"{row['project']}: {row['detail']}" for row in failed),
        data={"projects": rows},
    )


def _probe_project(project: str, workspace_dir: str) -> dict[str, object]:
    if not workspace_dir:
        return {
            "project": project,
            "workspace_dir": workspace_dir,
            "status": "skipped",
            "detail": "missing workspace dir",
        }
    try:
        if not supports_pull_requests(workspace_dir):
            return {
                "project": project,
                "workspace_dir": workspace_dir,
                "status": "skipped",
                "detail": "provider does not support pull-request listing",
            }
        provider = get_vcs_provider(workspace_dir)
        pull_requests = provider.list_pull_requests(
            workspace_dir,
            state="open",
            limit=1,
        )
    except Exception as exc:  # noqa: BLE001 - auth/network failures are the signal.
        return {
            "project": project,
            "workspace_dir": workspace_dir,
            "status": "error",
            "detail": f"{type(exc).__name__}: {exc}",
        }
    return {
        "project": project,
        "workspace_dir": workspace_dir,
        "status": "ok",
        "detail": (
            "open PR listing succeeded"
            if pull_requests
            else "open PR listing succeeded; no open PRs returned"
        ),
        "sample_count": len(pull_requests),
    }


@contextmanager
def _temporary_environ(env: dict[str, str]) -> Iterator[None]:
    original = dict(os.environ)
    try:
        os.environ.clear()
        os.environ.update(env)
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


__all__ = ["check_vcs_pull_requests"]
