"""Shared registry, override, and due findings for the flag doctor checks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal

from sase.bead.flag_due import flag_removal_due
from sase.feature_flags.beads import (
    LIVE_FLAG_STATUS_VALUES,
    FlagBeadSnapshot,
    flag_bead_for_id,
)
from sase.feature_flags.env import SASE_FEATURE_FLAGS_ENV, parse_feature_flags_env
from sase.feature_flags.models import (
    FeatureFlagDefinition,
    FeatureFlagEnvError,
    FeatureFlagSnapshot,
)
from sase.feature_flags.orphan import classify_orphan_bead


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
    *,
    checkout_committed_at: datetime | None = None,
    now: datetime | None = None,
) -> tuple[IntegrityFinding, ...]:
    """Both-direction registry/bead integrity (lint rules 1, 6, 7, and 8).

    Rule 8 (orphan bead) is an error for a live flag bead whose definition
    was deleted or never written, and a warning when the bead is still in
    the ``sase flag new`` landing window — see
    :func:`sase.feature_flags.orphan.classify_orphan_bead`.
    """
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
        if bead.task_type != "flag":
            findings.append(
                IntegrityFinding(
                    code="wrong_type",
                    severity="error",
                    message=(
                        f"feature flag {key!r} names bead {bead.id!r}, which "
                        f"is not a `flag` task bead"
                    ),
                    key=key,
                    bead_id=bead.id,
                )
            )
        if bead.kind and bead.kind != definition.kind:
            findings.append(
                IntegrityFinding(
                    code="kind_mismatch",
                    severity="error",
                    message=(
                        f"feature flag {key!r} has kind {definition.kind!r} "
                        f"but bead {bead.id!r} has kind {bead.kind!r}"
                    ),
                    key=key,
                    bead_id=bead.id,
                )
            )
        if definition.kind in {"beta", "sunset"}:
            expected_default = definition.kind == "sunset"
            if definition.default != expected_default:
                findings.append(
                    IntegrityFinding(
                        code="kind_mismatch",
                        severity="error",
                        message=(
                            f"feature flag {key!r} default "
                            f"{str(definition.default).lower()} disagrees "
                            f"with kind {definition.kind!r}"
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

    resolved_now = datetime.now(UTC) if now is None else now
    for bead in beads:
        if bead.status not in LIVE_FLAG_STATUS_VALUES:
            continue
        if bead.id in named_ids and bead.key in defined_keys:
            continue
        if bead.key in defined_keys:
            continue
        verdict = classify_orphan_bead(
            created_at=bead.created_at or None,
            created_by=bead.created_by or None,
            checkout_committed_at=checkout_committed_at,
            now=resolved_now,
        )
        message = f"live flag bead {bead.id!r} has no definition (key {bead.key!r})"
        if verdict.detail:
            message = f"{message}; {verdict.detail}"
        findings.append(
            IntegrityFinding(
                code="orphan_bead",
                severity=verdict.severity,
                message=message,
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
    if not bead.key or not bead.remove_by_date or not bead.remove_by_release:
        return None
    try:
        state = flag_removal_due(
            bead.remove_by_date,
            bead.remove_by_release,
            today=today,
            release=release,
        )
    except (IndexError, ValueError):
        return None
    if state == "due":
        return IntegrityFinding(
            code="due",
            severity="error",
            message=(
                f"feature flag {bead.key!r} is overdue "
                f"(remove_by {bead.remove_by_date} / {bead.remove_by_release})"
            ),
            key=key or bead.key,
            bead_id=bead.id,
        )
    if state == "soon":
        return IntegrityFinding(
            code="soon",
            severity="warning",
            message=(
                f"feature flag {bead.key!r} is approaching removal "
                f"(remove_by {bead.remove_by_date} / {bead.remove_by_release})"
            ),
            key=key or bead.key,
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
