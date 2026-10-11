"""Public-sidecar visibility check for private primaries in ``sase doctor``."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sase.bead.attachments.remote_visibility import resolve_remote_visibility
from sase.diagnostics import CheckSpec, DiagnosticCheck
from sase.doctor.checks_project import resolve_current_project_record
from sase.sdd._sidecar_visibility import resolve_primary_repo_visibility
from sase.sdd.store import read_sdd_store_record

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_CHECK_ID = "project.sidecar_visibility"
_TITLE = "Sidecar visibility"


def sidecar_visibility_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return the default check for public sidecars of a private primary."""

    return (
        CheckSpec(
            id=_CHECK_ID,
            group="project",
            title=_TITLE,
            runner=lambda: _check_sidecar_visibility(context),
        ),
    )


def _skip(summary: str) -> DiagnosticCheck:
    return DiagnosticCheck(
        id=_CHECK_ID,
        group="project",
        status="SKIP",
        title=_TITLE,
        summary=summary,
    )


def _check_sidecar_visibility(context: DoctorContext) -> DiagnosticCheck:
    """Warn about recorded sidecars that are public while the primary is private."""

    try:
        resolution = resolve_current_project_record(context)
    except Exception:
        return _skip("no current project; sidecar visibility check needs one")
    record = resolution.record
    workspace_dir = getattr(record, "workspace_dir", None)
    if (
        record is None
        or not isinstance(workspace_dir, str)
        or not workspace_dir.strip()
    ):
        return _skip("no current project; sidecar visibility check needs one")
    primary = Path(workspace_dir).expanduser()

    try:
        primary_visibility = resolve_primary_repo_visibility(primary)
    except Exception:
        return _skip(
            f"could not determine the primary visibility for {primary}; "
            "sidecar visibility check needs it"
        )
    if primary_visibility is None:
        return _skip(
            "the primary checkout has no hosted origin; "
            "sidecar visibility check needs one"
        )
    if primary_visibility.visibility != "private":
        return _skip(
            f"primary {primary_visibility.repo} is not private; "
            "sidecar visibility check needs a private primary"
        )

    try:
        store_record = read_sdd_store_record(primary)
    except Exception as exc:
        return _skip(
            f"could not read the sidecar store record for {primary_visibility.repo}: "
            f"{type(exc).__name__}: {exc}"
        )
    if (
        store_record is None
        or not store_record.is_sidecar_storage
        or not store_record.sidecars
    ):
        return _skip(
            f"project {primary_visibility.repo} has no recorded sidecar repositories"
        )

    public: list[tuple[str, str]] = []
    private: list[tuple[str, str]] = []
    unknown: list[tuple[str, str]] = []
    for role in sorted(store_record.sidecars):
        sidecar = store_record.sidecars[role]
        try:
            visibility = resolve_remote_visibility(sidecar.remote_url)
        except Exception:
            visibility = "unknown"
        if visibility == "public":
            public.append((role, sidecar.repo))
        elif visibility == "private":
            private.append((role, sidecar.repo))
        else:
            unknown.append((role, sidecar.repo))

    if public:
        details = [f"{role}: {repo} is public" for role, repo in public] + [
            f"gh repo edit {repo} --visibility private "
            "--accept-visibility-change-consequences"
            for _role, repo in public
        ]
        count = len(public)
        noun = "sidecar" if count == 1 else "sidecars"
        verb = "is" if count == 1 else "are"
        return DiagnosticCheck(
            id=_CHECK_ID,
            group="project",
            status="WARN",
            title=_TITLE,
            summary=(
                f"{count} recorded {noun} of private "
                f"{primary_visibility.repo} {verb} public"
            ),
            details=details,
        )

    total = len(private) + len(unknown)
    noun = "sidecar" if total == 1 else "sidecars"
    summary = (
        f"all {total} recorded {noun} of private {primary_visibility.repo} are private"
    )
    if unknown:
        count = len(unknown)
        noun = "sidecar" if count == 1 else "sidecars"
        summary += (
            f"; {count} recorded {noun} could not be verified "
            "and is treated as not public"
        )
    return DiagnosticCheck(
        id=_CHECK_ID,
        group="project",
        status="OK",
        title=_TITLE,
        summary=summary,
    )


__all__ = ["sidecar_visibility_check_specs"]
