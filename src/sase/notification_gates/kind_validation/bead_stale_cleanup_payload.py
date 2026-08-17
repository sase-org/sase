"""Structured payload parsing for BeadStaleCleanup gate validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from sase.bead._stale_cleanup_gate_preview import parse_stale_cleanup_instant
from sase.notification_gates.models import GateError

_BEAD_STALE_CLEANUP_PAYLOAD_FIELDS = frozenset(
    {
        "beads",
        "omitted_count",
        "min_plus_ones",
        "stale_after_days",
        "stale_cleanup_min_beads",
        "stale_as_of",
    }
)
_BEAD_STALE_CLEANUP_BEAD_FIELDS = frozenset(
    {
        "project",
        "bead_id",
        "title",
        "created_at",
        "plus_one_count",
        "size",
    }
)


@dataclass(frozen=True)
class _BeadStaleCleanupBead:
    """One offered stale task bead in a BeadStaleCleanup payload."""

    project: str
    bead_id: str
    title: str
    created_at: str
    plus_one_count: int
    size: str | None


@dataclass(frozen=True)
class BeadStaleCleanupPayload:
    """The validated, structurally typed view of a stale-cleanup gate payload."""

    beads: tuple[_BeadStaleCleanupBead, ...]
    omitted_count: int
    min_plus_ones: int
    stale_after_days: int
    stale_cleanup_min_beads: int
    stale_as_of: str


def parse_bead_stale_cleanup_payload(
    payload: Mapping[str, Any],
) -> BeadStaleCleanupPayload:
    """Validate *payload* against the structured BeadStaleCleanup contract."""
    from sase.bead._stale_cleanup_gate_spec import BEAD_STALE_CLEANUP_MAX_BEADS
    from sase.bead.model import PhaseSize
    from sase.core.paths import is_valid_sase_project_name

    if set(payload) != _BEAD_STALE_CLEANUP_PAYLOAD_FIELDS:
        raise GateError(
            "invalid_bead_stale_cleanup_payload",
            "payload",
            "bead stale cleanup payload does not match the structured "
            "presentation contract",
        )
    stale_as_of = _require_aware_instant(
        payload.get("stale_as_of"), field="stale_as_of"
    )
    omitted_count = _require_int(
        payload.get("omitted_count"), field="omitted_count", minimum=0
    )
    min_plus_ones = _require_int(
        payload.get("min_plus_ones"), field="min_plus_ones", minimum=0
    )
    stale_after_days = _require_int(
        payload.get("stale_after_days"), field="stale_after_days", minimum=1
    )
    stale_cleanup_min_beads = _require_int(
        payload.get("stale_cleanup_min_beads"),
        field="stale_cleanup_min_beads",
        minimum=1,
    )
    raw_beads = payload.get("beads")
    if not isinstance(raw_beads, list):
        raise GateError(
            "invalid_bead_stale_cleanup_payload",
            "payload.beads",
            "bead stale cleanup payload beads must be a non-empty array",
        )
    if not raw_beads:
        raise GateError(
            "invalid_bead_stale_cleanup_payload",
            "payload.beads",
            "bead stale cleanup payload beads must not be empty",
        )
    if len(raw_beads) > BEAD_STALE_CLEANUP_MAX_BEADS:
        raise GateError(
            "invalid_bead_stale_cleanup_payload",
            "payload.beads",
            f"bead stale cleanup payload beads exceed {BEAD_STALE_CLEANUP_MAX_BEADS}",
        )
    beads: list[_BeadStaleCleanupBead] = []
    seen: set[tuple[str, str]] = set()
    valid_sizes = {item.value for item in PhaseSize}
    for index, raw_bead in enumerate(raw_beads):
        target = f"payload.beads[{index}]"
        if not isinstance(raw_bead, Mapping) or set(raw_bead) != (
            _BEAD_STALE_CLEANUP_BEAD_FIELDS
        ):
            raise GateError(
                "invalid_bead_stale_cleanup_payload",
                target,
                "bead stale cleanup bead does not match the structured "
                "presentation contract",
            )
        project = raw_bead.get("project")
        if not isinstance(project, str) or not is_valid_sase_project_name(project):
            raise GateError(
                "invalid_bead_stale_cleanup_payload",
                f"{target}.project",
                "bead stale cleanup payload requires a canonical SASE project key",
            )
        bead_id = raw_bead.get("bead_id")
        if not isinstance(bead_id, str) or not bead_id.strip():
            raise GateError(
                "invalid_bead_stale_cleanup_payload",
                f"{target}.bead_id",
                "bead stale cleanup payload requires bead_id",
            )
        identity = (project, bead_id)
        if identity in seen:
            raise GateError(
                "invalid_bead_stale_cleanup_payload",
                target,
                "bead stale cleanup payload has a duplicate (project, bead_id)",
            )
        seen.add(identity)
        title = raw_bead.get("title")
        if not isinstance(title, str):
            raise GateError(
                "invalid_bead_stale_cleanup_payload",
                f"{target}.title",
                "bead stale cleanup payload title must be a string",
            )
        created_at = raw_bead.get("created_at")
        _require_aware_instant(created_at, field=f"beads[{index}].created_at")
        plus_one_count = _require_int(
            raw_bead.get("plus_one_count"),
            field=f"beads[{index}].plus_one_count",
            minimum=0,
        )
        size = raw_bead.get("size")
        if size is not None and (not isinstance(size, str) or size not in valid_sizes):
            raise GateError(
                "invalid_bead_stale_cleanup_payload",
                f"{target}.size",
                "bead stale cleanup payload size must be null or a valid task size",
            )
        beads.append(
            _BeadStaleCleanupBead(
                project=project,
                bead_id=bead_id,
                title=title,
                created_at=cast(str, created_at),
                plus_one_count=plus_one_count,
                size=cast("str | None", size),
            )
        )
    return BeadStaleCleanupPayload(
        beads=tuple(beads),
        omitted_count=omitted_count,
        min_plus_ones=min_plus_ones,
        stale_after_days=stale_after_days,
        stale_cleanup_min_beads=stale_cleanup_min_beads,
        stale_as_of=stale_as_of,
    )


def _require_aware_instant(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GateError(
            "invalid_bead_stale_cleanup_payload",
            f"payload.{field}",
            f"bead stale cleanup payload requires {field}",
        )
    try:
        parse_stale_cleanup_instant(value)
    except ValueError as exc:
        raise GateError(
            "invalid_bead_stale_cleanup_payload",
            f"payload.{field}",
            f"bead stale cleanup payload {field} must be a timezone-aware "
            "ISO-8601 instant",
        ) from exc
    return value


def _require_int(value: object, *, field: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise GateError(
            "invalid_bead_stale_cleanup_payload",
            f"payload.{field}",
            f"bead stale cleanup payload {field} must be an integer >= {minimum}",
        )
    return value


__all__ = [
    "BeadStaleCleanupPayload",
    "parse_bead_stale_cleanup_payload",
]
