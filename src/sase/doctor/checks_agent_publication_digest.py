"""Doctor check for agents-sidecar hood-snapshot digest drift.

An out-of-band rewrite of an already-published payload file (for example a
direct edit to a published ``chat.md``) leaves the snapshot's signed digest
stale. This reuses the exact repair-planning logic in
``sase.agents_sync.publication_repair`` in dry-run form, so the check and
the remediation it points at can never disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.publication_repair import (
    REPAIR_DIGESTS_COMMAND,
    repair_owner_hood_digests,
)
from sase.agents_sync.targets import resolve_sync_targets
from sase.config import require_agent_owner_identity
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import is_disabled_project_lifecycle_state
from sase.diagnostics import CheckSpec, DiagnosticCheck

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_MAX_DETAIL_ROWS = 10


@dataclass(frozen=True, slots=True)
class _DigestDriftProblem:
    project_key: str
    project: str
    paths: tuple[str, ...]

    def detail(self) -> str:
        visible = ", ".join(self.paths[:3])
        remaining = len(self.paths) - 3
        more = f" (+{remaining} more)" if remaining > 0 else ""
        return f"{self.project}: {len(self.paths)} drifted file(s): {visible}{more}"

    def to_data(self) -> dict[str, object]:
        return {
            "project_key": self.project_key,
            "project": self.project,
            "drifted_file_count": len(self.paths),
            "drifted_files": self.paths,
        }


def agent_publication_digest_check_specs(
    context: DoctorContext,
) -> tuple[CheckSpec, ...]:
    """Return the default agents-sidecar digest-drift check spec."""
    return (
        CheckSpec(
            id="state.agent_publication_digest",
            group="state",
            title="Agent publication digest",
            runner=lambda: _check_agent_publication_digest(context),
        ),
    )


def _check_agent_publication_digest(context: DoctorContext) -> DiagnosticCheck:
    try:
        records = tuple(
            list_project_records(
                context.sase_home / "projects",
                "all",
                include_home=False,
                projects_only=True,
            )
        )
    except FileNotFoundError:
        return DiagnosticCheck(
            id="state.agent_publication_digest",
            group="state",
            status="SKIP",
            title="Agent publication digest",
            summary="SASE projects directory is not present",
        )

    enabled_projects = tuple(
        record.project_name
        for record in records
        if record.is_project and not is_disabled_project_lifecycle_state(record.state)
    )
    if not enabled_projects:
        return DiagnosticCheck(
            id="state.agent_publication_digest",
            group="state",
            status="SKIP",
            title="Agent publication digest",
            summary="no enabled SASE projects are registered",
        )

    try:
        owner = require_agent_owner_identity()
    except (RuntimeError, ValueError) as exc:
        return DiagnosticCheck(
            id="state.agent_publication_digest",
            group="state",
            status="SKIP",
            title="Agent publication digest",
            summary=f"owner identity is not configured: {exc}",
        )

    try:
        selection = resolve_sync_targets(
            enabled_projects,
            projects_root=context.sase_home / "projects",
        )
    except Exception as exc:  # noqa: BLE001 - doctor isolates target resolution.
        return DiagnosticCheck(
            id="state.agent_publication_digest",
            group="state",
            status="ERROR",
            title="Agent publication digest",
            summary="could not resolve agents sidecar targets",
            details=(f"{type(exc).__name__}: {exc}",),
        )

    problems: list[_DigestDriftProblem] = []
    errors: list[str] = []
    for target in selection.targets:
        try:
            _payload, resigned = repair_owner_hood_digests(
                target, target.sidecar_path, owner
            )
        except (AgentsSyncFormatError, OSError, RuntimeError, ValueError) as exc:
            errors.append(f"{target.project}: could not check digests: {exc}")
            continue
        if resigned:
            problems.append(
                _DigestDriftProblem(target.project_key, target.project, resigned)
            )

    target_errors = tuple(
        f"{outcome.project}: {outcome.error or outcome.skip_reason}"
        for outcome in selection.outcomes
        if outcome.error or outcome.skip_reason
    )
    all_errors = (*errors, *target_errors)

    if problems:
        visible = problems[:_MAX_DETAIL_ROWS]
        drifted_count = sum(len(problem.paths) for problem in problems)
        return DiagnosticCheck(
            id="state.agent_publication_digest",
            group="state",
            status="WARN",
            title="Agent publication digest",
            summary=(
                f"{drifted_count} drifted file(s) across {len(problems)} project(s); "
                f"run `{REPAIR_DIGESTS_COMMAND}`"
            ),
            details=tuple(problem.detail() for problem in visible),
            next_steps=(
                f"Run `{REPAIR_DIGESTS_COMMAND}` to re-sign the affected hood "
                "snapshots from their on-disk payload.",
            ),
            data={
                "problems": tuple(problem.to_data() for problem in problems),
                "details_truncated": len(problems) > len(visible),
                "errors": all_errors,
            },
        )

    if all_errors:
        return DiagnosticCheck(
            id="state.agent_publication_digest",
            group="state",
            status="ERROR",
            title="Agent publication digest",
            summary=f"{len(all_errors)} project(s) could not be checked for digest drift",
            details=tuple(all_errors[:_MAX_DETAIL_ROWS]),
            data={"errors": all_errors},
        )

    return DiagnosticCheck(
        id="state.agent_publication_digest",
        group="state",
        status="OK",
        title="Agent publication digest",
        summary="no hood-snapshot digest drift detected",
        data={"problems": (), "errors": ()},
    )


__all__ = ["agent_publication_digest_check_specs"]
