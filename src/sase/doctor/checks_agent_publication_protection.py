"""Doctor reporting for private agents-publication protection records."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.agents_sync.publication_protection import (
    AGENT_PUBLICATION_PROTECTION_FILENAME,
    read_publication_protection_ledger_from_path,
)
from sase.core.agent_publication_protection import (
    publication_protection_record_enforced,
)
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import effective_project_name
from sase.diagnostics import CheckSpec, DiagnosticCheck

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_MAX_DETAIL_ROWS = 10


def agent_publication_protection_check_specs(
    context: DoctorContext,
) -> tuple[CheckSpec, ...]:
    """Return the private content-protection check spec."""
    return (
        CheckSpec(
            id="state.agent_publication_protection",
            group="state",
            title="Agent publication protection",
            runner=lambda: _check_agent_publication_protection(context),
        ),
    )


def _check_agent_publication_protection(
    context: DoctorContext,
) -> DiagnosticCheck:
    projects_root = context.sase_home / "projects"
    try:
        records = tuple(
            list_project_records(
                projects_root,
                "all",
                include_home=False,
                projects_only=True,
            )
        )
    except FileNotFoundError:
        return DiagnosticCheck(
            id="state.agent_publication_protection",
            group="state",
            status="SKIP",
            title="Agent publication protection",
            summary="SASE projects directory is not present",
            data={"projects_root": str(projects_root), "record_count": 0},
        )
    except Exception:  # noqa: BLE001 - keep doctor free of untrusted state text.
        return DiagnosticCheck(
            id="state.agent_publication_protection",
            group="state",
            status="ERROR",
            title="Agent publication protection",
            summary="project records could not be loaded",
            data={"projects_root": str(projects_root), "error_count": 1},
        )

    details: list[str] = []
    safe_rows: list[dict[str, object]] = []
    errors: list[str] = []
    blocked_count = 0
    stale_count = 0
    unverified_count = 0
    superseded_count = 0
    for project in records:
        path = (
            projects_root / project.project_name / AGENT_PUBLICATION_PROTECTION_FILENAME
        )
        try:
            ledger = read_publication_protection_ledger_from_path(
                path,
                project.project_name,
            )
        except Exception:  # noqa: BLE001 - never echo persisted content or parser detail.
            errors.append(effective_project_name(project))
            continue
        if ledger is None:
            continue
        rows = ledger.get("records")
        superseded = ledger.get("superseded", [])
        if not isinstance(rows, list) or not isinstance(superseded, list):
            errors.append(effective_project_name(project))
            continue
        superseded_count += len(superseded)
        for row in rows:
            if not isinstance(row, dict):
                errors.append(effective_project_name(project))
                continue
            status = row.get("status")
            destination = row.get("relative_destination")
            if status not in {"blocked", "unverified"} or not isinstance(
                destination, str
            ):
                errors.append(effective_project_name(project))
                continue
            evidence = row.get("evidence")
            rule_ids: list[str] = []
            if isinstance(evidence, list):
                for hit in evidence:
                    if isinstance(hit, dict):
                        rule_id = hit.get("rule_id")
                        if isinstance(rule_id, str):
                            rule_ids.append(rule_id)
            rule_ids = sorted(set(rule_ids))
            if status == "blocked":
                try:
                    enforced = publication_protection_record_enforced(row)
                except Exception:  # noqa: BLE001 - keep doctor free of stored values.
                    errors.append(effective_project_name(project))
                    continue
                if enforced:
                    blocked_count += 1
                else:
                    status = "stale"
                    stale_count += 1
            else:
                unverified_count += 1
            safe_row = {
                "project_key": project.project_name,
                "project": effective_project_name(project),
                "status": status,
                "reason": row.get("reason"),
                "relative_destination": destination,
                "rule_ids": rule_ids,
                "rules_versions": row.get("rules_versions", []),
            }
            safe_rows.append(safe_row)
            rules = f"; rules: {', '.join(rule_ids)}" if rule_ids else ""
            if status == "stale":
                details.append(
                    f"{effective_project_name(project)}: stale scanner block at "
                    f"{destination} awaits revalidation{rules}"
                )
            else:
                details.append(
                    f"{effective_project_name(project)}: {status} content at "
                    f"{destination}{rules}"
                )

    base_data: dict[str, Any] = {
        "projects_root": str(projects_root),
        "record_count": len(records),
        "blocked_count": blocked_count,
        "stale_count": stale_count,
        "unverified_count": unverified_count,
        "superseded_count": superseded_count,
        "error_count": len(errors),
        "errors": tuple(errors),
        "records": tuple(safe_rows),
    }
    if errors:
        return DiagnosticCheck(
            id="state.agent_publication_protection",
            group="state",
            status="ERROR",
            title="Agent publication protection",
            summary=(
                f"{len(errors)} project publication-protection ledger(s) could not be read"
            ),
            details=tuple(
                f"{project}: protection ledger is invalid"
                for project in errors[:_MAX_DETAIL_ROWS]
            ),
            next_steps=(
                "Inspect the private agents-publication-protection.json file and repair its schema.",
            ),
            data={**base_data, "details_truncated": len(errors) > _MAX_DETAIL_ROWS},
        )

    if blocked_count or stale_count or unverified_count:
        next_steps: list[str] = []
        if blocked_count:
            next_steps.append(
                "Sanitize blocked source content and publish its changed digest; blocked bytes remain withheld."
            )
        if stale_count:
            next_steps.append(
                "Retry publication to rescan stale scanner-hit blocks under the current rules."
            )
        if unverified_count:
            next_steps.append(
                "Retry unverified content only after the scanner can inspect it within its configured text limit."
            )
        return DiagnosticCheck(
            id="state.agent_publication_protection",
            group="state",
            status="WARN",
            title="Agent publication protection",
            summary=(
                f"{blocked_count} enforced blocked, {stale_count} stale awaiting "
                f"revalidation, and {unverified_count} unverified publication "
                f"record(s) remain; {superseded_count} superseded record(s) retained"
            ),
            details=tuple(details[:_MAX_DETAIL_ROWS]),
            next_steps=tuple(next_steps),
            data={**base_data, "details_truncated": len(details) > _MAX_DETAIL_ROWS},
        )

    return DiagnosticCheck(
        id="state.agent_publication_protection",
        group="state",
        status="OK",
        title="Agent publication protection",
        summary=(
            "no blocked or unverified publication content is recorded; "
            f"{superseded_count} superseded record(s) retained"
        ),
        data=base_data,
    )


__all__ = [
    "agent_publication_protection_check_specs",
]
