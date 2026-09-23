"""Python facade for durable per-clan attribute records.

One JSON file per clan lives under ``<sase_home>/agent_clans/`` and maps
artifact-directory generation names to the clan's recorded ``tribe``,
``summary``, and ``summary_script`` attributes. The Rust ``sase-core`` crate
owns the schema, merge rules, locking, and I/O; this module is a thin typed
wrapper over the four ``sase_core_rs`` bindings.

Launch and cleanup callers use the default best-effort mode (``strict=False``):
a missing/stale wheel or a record error is logged and swallowed so it can
never block a launch or a deletion. User-initiated edits pass ``strict=True``
so failures surface as directive errors.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home
from sase.core.rust import require_rust_binding

log = logging.getLogger(__name__)

AGENT_CLAN_RECORDS_DIR_NAME = "agent_clans"


def clan_records_dir(sase_home_dir: Path | str | None = None) -> Path:
    """Return the directory holding per-clan record files."""
    root = (
        Path(sase_home_dir).expanduser() if sase_home_dir is not None else sase_home()
    )
    return root / AGENT_CLAN_RECORDS_DIR_NAME


def _records_dir_str(records_dir: Path | str | None) -> str:
    if records_dir is None:
        return str(clan_records_dir())
    return str(Path(records_dir).expanduser())


def clan_attribute_update(
    value: str | None,
    source: str,
    *,
    source_identity: str | None = None,
) -> dict[str, Any]:
    """Build one ``ClanAttributeUpdateWire`` dict for a record update."""
    return {
        "value": value,
        "source": source,
        "source_identity": source_identity,
    }


def load_clan_record(
    clan: str,
    *,
    records_dir: Path | str | None = None,
    strict: bool = False,
) -> dict[str, Any] | None:
    """Return one clan's durable record dict, or ``None`` when absent.

    Corrupt files surface as errors from the binding; in best-effort mode
    they are logged and reported as absent so readers fall back to
    member-derived values.
    """
    try:
        binding = require_rust_binding("load_agent_clan_record")
        return binding(_records_dir_str(records_dir), clan)
    except Exception as exc:  # noqa: BLE001 - record reads are best-effort.
        if strict:
            raise
        log.warning("Skipping clan record read for %r: %s", clan, exc)
        return None


def record_clan_attributes(
    update: dict[str, Any],
    *,
    records_dir: Path | str | None = None,
    strict: bool = False,
) -> dict[str, Any] | None:
    """Merge one ``ClanRecordUpdateWire`` dict and return the outcome dict.

    Returns ``None`` (after logging) instead of raising when ``strict`` is
    false so launch and cleanup paths stay best-effort.
    """
    try:
        binding = require_rust_binding("record_agent_clan_attributes")
        return dict(binding(_records_dir_str(records_dir), dict(update)))
    except Exception as exc:  # noqa: BLE001 - launch/cleanup are best-effort.
        if strict:
            raise
        log.warning("Skipping clan record write for %r: %s", update.get("clan"), exc)
        return None


def capture_clan_record_from_artifacts(
    artifacts_dir: Path | str,
    *,
    records_dir: Path | str | None = None,
    strict: bool = False,
) -> dict[str, Any] | None:
    """Capture a dying artifact directory's clan attributes as ``captured``.

    Returns the clan record dict, or ``None`` when the directory carries
    nothing to capture (or when a best-effort capture fails).
    """
    try:
        binding = require_rust_binding("capture_agent_clan_record_from_artifacts")
        result = binding(_records_dir_str(records_dir), str(artifacts_dir))
        return dict(result) if result is not None else None
    except Exception as exc:  # noqa: BLE001 - capture never blocks deletion.
        if strict:
            raise
        log.warning("Skipping clan record capture for %s: %s", artifacts_dir, exc)
        return None


def resolve_clan_launch_defaults(
    clan: str,
    *,
    exclude_generation: str | None = None,
    records_dir: Path | str | None = None,
    strict: bool = False,
) -> dict[str, Any] | None:
    """Return remembered attributes seeding a new generation of *clan*."""
    try:
        binding = require_rust_binding("resolve_agent_clan_launch_defaults")
        return dict(binding(_records_dir_str(records_dir), clan, exclude_generation))
    except Exception as exc:  # noqa: BLE001 - launch defaults are best-effort.
        if strict:
            raise
        log.warning("Skipping clan launch defaults for %r: %s", clan, exc)
        return None


__all__ = [
    "AGENT_CLAN_RECORDS_DIR_NAME",
    "capture_clan_record_from_artifacts",
    "clan_attribute_update",
    "clan_records_dir",
    "load_clan_record",
    "record_clan_attributes",
    "resolve_clan_launch_defaults",
]
