"""Footprint spool checks for ``sase doctor``."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from sase.diagnostics import CheckSpec, DiagnosticCheck
from sase.footprint.paths import MODE_LOCAL, effective_mode

if TYPE_CHECKING:
    from sase.doctor.runner import DoctorContext

_STALE_SPOOL_AGE = timedelta(days=3)


def footprint_check_specs(context: DoctorContext) -> tuple[CheckSpec, ...]:
    """Return the local Footprint spool health check."""
    return (
        CheckSpec(
            id="ops.footprint_spool",
            group="ops",
            title="Footprint spool",
            runner=lambda: _check_footprint_spool(context),
        ),
    )


def _check_footprint_spool(
    context: DoctorContext,
    *,
    today: date | None = None,
) -> DiagnosticCheck:
    """Warn when local recording has spool bytes older than three days."""
    home = Path(context.sase_home)
    mode = effective_mode(context.env, home / "footprint" / "mode")
    if mode != MODE_LOCAL:
        return DiagnosticCheck(
            id="ops.footprint_spool",
            group="ops",
            status="SKIP",
            title="Footprint spool",
            summary=f"Footprint recording mode is {mode}",
            data={"mode": mode, "stale_files": ()},
        )

    spool_dir = home / "footprint" / "spool"
    if not spool_dir.is_dir():
        return _healthy()
    current_day = today or date.today()
    cutoff = current_day - _STALE_SPOOL_AGE
    stale_candidates: list[Path] = []
    for path in spool_dir.glob("*.jsonl"):
        spool_day = _spool_day(path)
        if spool_day is not None and spool_day < cutoff:
            stale_candidates.append(path)
    if not stale_candidates:
        return _healthy()

    from sase.core.footprint_facade import (
        footprint_ledger_path,
        footprint_status,
    )

    try:
        snapshot = footprint_status(
            footprint_ledger_path(home),
            spool_dir,
            current_day.isoformat(),
            busy_timeout_ms=100,
        )
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        return DiagnosticCheck(
            id="ops.footprint_spool",
            group="ops",
            status="WARN",
            title="Footprint spool",
            summary="could not check whether older spool records were folded",
            details=(f"{type(exc).__name__}: {exc}",),
            next_steps=("Run `sase footprint status`, then rerun `sase doctor`.",),
            data={"mode": mode, "status_error": type(exc).__name__},
        )

    pending = snapshot.get("spool_pending")
    pending_by_file: dict[str, int] = {}
    if isinstance(pending, list):
        for item in pending:
            if not isinstance(item, dict):
                continue
            try:
                pending_by_file[str(item["file"])] = int(item["bytes_pending"])
            except (KeyError, TypeError, ValueError):
                continue
    stale = sorted(
        (path.name, pending_by_file.get(path.name, 0))
        for path in stale_candidates
        if pending_by_file.get(path.name, 0) > 0
    )
    if not stale:
        return _healthy()

    oldest = min(name[:-6] for name, _size in stale)
    pending_bytes = sum(size for _name, size in stale)
    return DiagnosticCheck(
        id="ops.footprint_spool",
        group="ops",
        status="WARN",
        title="Footprint spool",
        summary=(
            f"{pending_bytes} unfolded byte(s) remain from {oldest}; "
            "the spool is older than three days"
        ),
        details=tuple(f"{name}: {size} pending byte(s)" for name, size in stale),
        next_steps=("Run `sase footprint status` to retry the fold.",),
        data={
            "mode": mode,
            "stale_files": tuple(name for name, _size in stale),
            "pending_bytes": pending_bytes,
            "oldest_day": oldest,
        },
    )


def _healthy() -> DiagnosticCheck:
    return DiagnosticCheck(
        id="ops.footprint_spool",
        group="ops",
        status="OK",
        title="Footprint spool",
        summary="no unfolded Footprint spool older than three days",
        data={"stale_files": ()},
    )


def _spool_day(path: Path) -> date | None:
    try:
        parsed = date.fromisoformat(path.stem)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == path.stem else None


__all__ = ["footprint_check_specs"]
