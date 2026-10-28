"""Fold existing usage sources into the Footprint ledger as derived rows."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import logging
from pathlib import Path
from typing import Any

from sase.core.footprint_facade import (
    footprint_ledger_path,
    footprint_upsert_derived,
)
from sase.core.time import local_now
from sase.footprint.catalog import load_catalog
from sase.footprint.derived_auto import ORIGIN as AUTO_ORIGIN
from sase.footprint.derived_auto import extract_auto_rows
from sase.footprint.derived_config import ORIGIN as CONFIG_ORIGIN
from sase.footprint.derived_config import extract_config_rows
from sase.footprint.derived_macros import ORIGIN as MACROS_ORIGIN
from sase.footprint.derived_macros import extract_macro_rows
from sase.footprint.derived_rows import assert_row_allowlist
from sase.footprint.derived_skills import ORIGIN as SKILLS_ORIGIN
from sase.footprint.derived_skills import extract_skill_rows
from sase.footprint.paths import sase_home as default_sase_home

_LOG = logging.getLogger(__name__)
_BUSY_TIMEOUT_MS = 75

Extractor = Callable[..., tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]]


def _hourly_sources() -> tuple[tuple[str, Extractor], ...]:
    # Look up extractors at call time so tests can replace the module names.
    return (
        (MACROS_ORIGIN, extract_macro_rows),
        (SKILLS_ORIGIN, extract_skill_rows),
        (CONFIG_ORIGIN, extract_config_rows),
        (AUTO_ORIGIN, extract_auto_rows),
    )


def fold_derived_sources(
    *,
    sase_home: Path | None = None,
    today: str | None = None,
    catalog_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Recompute hourly derived origins. One source failure leaves the others."""
    home = Path(sase_home) if sase_home is not None else default_sase_home()
    day = today or local_now().date().isoformat()
    ids = catalog_ids if catalog_ids is not None else _catalog_ids()
    store = footprint_ledger_path(home)
    results: dict[str, Any] = {}
    for origin, extractor in _hourly_sources():
        results[origin] = _fold_one(store, origin, extractor, ids, day)
    return results


def upsert_origin(
    origin: str,
    days: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    coverage: Sequence[Mapping[str, Any]],
    *,
    sase_home: Path | None = None,
) -> None:
    """Replace *origin* for *days* after validating the row allowlist."""
    assert_row_allowlist(rows)
    home = Path(sase_home) if sase_home is not None else default_sase_home()
    footprint_upsert_derived(
        footprint_ledger_path(home),
        origin,
        days,
        rows,
        coverage,
        busy_timeout_ms=_BUSY_TIMEOUT_MS,
    )


def _fold_one(
    store: Path,
    origin: str,
    extractor: Extractor,
    catalog_ids: set[str],
    today: str,
) -> dict[str, Any]:
    try:
        days, rows, coverage = extractor(catalog_ids=catalog_ids, today=today)
        assert_row_allowlist(rows)
        footprint_upsert_derived(
            store,
            origin,
            days,
            rows,
            coverage,
            busy_timeout_ms=_BUSY_TIMEOUT_MS,
        )
    except Exception:  # noqa: BLE001 - one source must not wipe another origin.
        _LOG.warning("Footprint derived source %s failed", origin, exc_info=True)
        return {"ok": False, "rows": 0, "days": 0}
    return {"ok": True, "rows": len(rows), "days": len(days)}


def _catalog_ids() -> set[str]:
    _header, entries = load_catalog()
    return {entry.id for entry in entries}


__all__ = ["fold_derived_sources", "upsert_origin"]
