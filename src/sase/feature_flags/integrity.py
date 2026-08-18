"""Shared registry, override, and due findings for the flag doctor checks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from sase.bead.flag_due import flag_removal_due
from sase.feature_flags.beads import (
    LIVE_FLAG_STATUS_VALUES,
    FlagBeadSnapshot,
    flag_bead_for_id,
    flag_record_from_snapshot,
)
from sase.feature_flags.env import SASE_FEATURE_FLAGS_ENV, parse_feature_flags_env
from sase.feature_flags.models import (
    FeatureFlagDefinition,
    FeatureFlagEnvError,
    FeatureFlagSnapshot,
)


IntegritySeverity = Literal["error", "warning"]


@dataclass(frozen=True)
class IntegrityFinding:
    """One registry, override, or due finding."""

    code: str
    severity: IntegritySeverity
    message: str
    key: str | None = None
    bead_id: str | None = None


def registry_integrity_findings(
    definitions: Mapping[str, FeatureFlagDefinition],
    beads: Sequence[FlagBeadSnapshot],
) -> tuple[IntegrityFinding, ...]:
    """Both-direction registry/bead integrity (lint rules 1, 6, 7, and 8)."""
    findings: list[IntegrityFinding] = []
    defined_keys = set(definitions)
    named_ids = {
        definition.bead for definition in definitions.values() if definition.bead
    }

    for key, definition in sorted(definitions.items()):
        try:
            definition.validate()
        except Exception as exc:  # noqa: BLE001 - surface the definition's own wording.
            findings.append(
                IntegrityFinding(
                    code="definition",
                    severity="error",
                    message=str(exc),
                    key=key,
                    bead_id=definition.bead,
                )
            )
            continue
        if not definition.bead:
            continue
        bead = flag_bead_for_id(tuple(beads), definition.bead)
        if bead is None:
            findings.append(
                IntegrityFinding(
                    code="missing_bead",
                    severity="error",
                    message=(
                        f"feature flag {key!r} names missing bead {definition.bead!r}"
                    ),
                    key=key,
                    bead_id=definition.bead,
                )
            )
            continue
        if bead.issue_type != "flag":
            findings.append(
                IntegrityFinding(
                    code="wrong_type",
                    severity="error",
                    message=(
                        f"feature flag {key!r} names bead {bead.id!r} of type "
                        f"{bead.issue_type!r}, expected 'flag'"
                    ),
                    key=key,
                    bead_id=bead.id,
                )
            )
        if bead.key != key:
            findings.append(
                IntegrityFinding(
                    code="key_mismatch",
                    severity="error",
                    message=(
                        f"feature flag {key!r} names bead {bead.id!r} whose "
                        f"key is {bead.key!r}"
                    ),
                    key=key,
                    bead_id=bead.id,
                )
            )
        if bead.status == "closed":
            findings.append(
                IntegrityFinding(
                    code="closed_survives",
                    severity="error",
                    message=(
                        f"closed flag bead {bead.id!r} still has a surviving "
                        f"{key!r} definition"
                    ),
                    key=key,
                    bead_id=bead.id,
                )
            )

    for bead in beads:
        if bead.status not in LIVE_FLAG_STATUS_VALUES:
            continue
        if bead.id in named_ids and bead.key in defined_keys:
            continue
        if bead.key in defined_keys:
            continue
        findings.append(
            IntegrityFinding(
                code="orphan_bead",
                severity="error",
                message=(
                    f"live flag bead {bead.id!r} has no definition (key {bead.key!r})"
                ),
                key=bead.key,
                bead_id=bead.id,
            )
        )
    return tuple(findings)


def due_integrity_findings(
    definitions: Mapping[str, FeatureFlagDefinition],
    beads: Sequence[FlagBeadSnapshot],
    *,
    today: date,
    release: str,
) -> tuple[IntegrityFinding, ...]:
    """Overdue and soon-due findings for live flag beads named by the registry."""
    findings: list[IntegrityFinding] = []
    seen: set[str] = set()
    for key, definition in sorted(definitions.items()):
        if not definition.bead:
            continue
        bead = flag_bead_for_id(tuple(beads), definition.bead)
        if bead is None:
            continue
        finding = _due_finding(bead, today=today, release=release, key=key)
        if finding is not None:
            findings.append(finding)
            seen.add(bead.id)

    for bead in beads:
        if bead.id in seen or bead.status not in LIVE_FLAG_STATUS_VALUES:
            continue
        finding = _due_finding(bead, today=today, release=release, key=bead.key)
        if finding is not None:
            findings.append(finding)
    return tuple(findings)


def override_integrity_findings(
    snapshot: FeatureFlagSnapshot,
    *,
    env_raw: str | None,
) -> tuple[IntegrityFinding, ...]:
    """Unknown keys, bad values, scope violations, and inherited env overrides."""
    if env_raw is not None:
        try:
            parse_feature_flags_env(env_raw)
        except FeatureFlagEnvError as exc:
            return (
                IntegrityFinding(
                    code="malformed_env",
                    severity="error",
                    message=str(exc),
                ),
            )

    findings: list[IntegrityFinding] = []
    for diagnostic in snapshot.diagnostics:
        findings.append(
            IntegrityFinding(
                code=diagnostic.code,
                severity="warning",
                message=f"{diagnostic.source}: {diagnostic.message}",
            )
        )
    for decision in snapshot.non_default():
        if decision.source != "env":
            continue
        env_name = decision.source_detail or SASE_FEATURE_FLAGS_ENV
        if env_name != SASE_FEATURE_FLAGS_ENV:
            continue
        findings.append(
            IntegrityFinding(
                code="env_inherited",
                severity="warning",
                message=(
                    f"feature flag {decision.key!r} is inherited from "
                    f"{env_name} "
                    f"({decision.key}={str(decision.enabled).lower()})"
                ),
                key=decision.key,
            )
        )
    return tuple(findings)


def _due_finding(
    bead: FlagBeadSnapshot,
    *,
    today: date,
    release: str,
    key: str | None,
) -> IntegrityFinding | None:
    if bead.status not in LIVE_FLAG_STATUS_VALUES:
        return None
    record = flag_record_from_snapshot(bead)
    if record is None:
        return None
    try:
        state = flag_removal_due(record, today=today, release=release)
    except (IndexError, ValueError):
        return None
    if state == "due":
        return IntegrityFinding(
            code="due",
            severity="error",
            message=(
                f"feature flag {record.key!r} is overdue "
                f"(remove_by {record.remove_by_date} / {record.remove_by_release})"
            ),
            key=key or record.key,
            bead_id=bead.id,
        )
    if state == "soon":
        return IntegrityFinding(
            code="soon",
            severity="warning",
            message=(
                f"feature flag {record.key!r} is approaching removal "
                f"(remove_by {record.remove_by_date} / {record.remove_by_release})"
            ),
            key=key or record.key,
            bead_id=bead.id,
        )
    return None


__all__ = [
    "IntegrityFinding",
    "IntegritySeverity",
    "due_integrity_findings",
    "override_integrity_findings",
    "registry_integrity_findings",
]
