"""Python driver for catalog ingest, spool folding, retention, and clear."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
import logging
import os
from pathlib import Path
import tempfile
from typing import Any

from sase.core.footprint_facade import (
    footprint_catalog_status,
    footprint_clear,
    footprint_fold,
    footprint_ingest_catalog,
    footprint_ledger_path,
    footprint_prune,
    footprint_spool_dir,
    footprint_status,
)
from sase.footprint.carrying_cost import carrying_cost_enrichment
from sase.footprint.catalog import catalog_path, load_catalog
from sase.footprint.paths import (
    generation_path,
    sase_home as default_sase_home,
)

_LOG = logging.getLogger(__name__)
_BUSY_TIMEOUT_MS = 75
_STATUS_RETRY_TIMEOUT_MS = 250
_FOLD_MAX_AGE = timedelta(minutes=10)
_DEFAULTS: dict[str, int] = {
    "retention_days": 400,
    "spool_keep_days": 7,
    "spool_max_age_days": 30,
}


def fold_ledger(
    *,
    sase_home: Path | None = None,
    today: str | None = None,
    initial_status: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Ingest a new catalog revision, fold spool records, and prune old rows.

    Busy ledger locks are a normal skip: the previous snapshot is returned so
    callers can continue to display the ledger as it stood before contention.
    """
    home = Path(sase_home) if sase_home is not None else default_sase_home()
    day = today or date.today().isoformat()
    before = dict(initial_status) if initial_status is not None else None
    if before is None:
        try:
            before = _read_status(home, day, _BUSY_TIMEOUT_MS)
        except TimeoutError:
            status = _status_after_contention(home, day, {})
            return {
                "folded": False,
                "reason": "lock_contended",
                "fold": {},
                "prune": {},
                "status": status,
            }

    store = footprint_ledger_path(home)
    spool = footprint_spool_dir(home)
    catalog = catalog_path()
    settings = _footprint_settings()

    try:
        catalog_state = footprint_catalog_status(
            store, catalog, busy_timeout_ms=_BUSY_TIMEOUT_MS
        )
        if not bool(catalog_state.get("known")):
            _header, entries = load_catalog(catalog)
            enrichment = carrying_cost_enrichment(entries)
            footprint_ingest_catalog(
                store,
                catalog,
                enrichment,
                day,
                busy_timeout_ms=_BUSY_TIMEOUT_MS,
            )
        folded = footprint_fold(
            store,
            spool,
            day,
            settings["spool_keep_days"],
            settings["spool_max_age_days"],
            busy_timeout_ms=_BUSY_TIMEOUT_MS,
        )
    except TimeoutError:
        status = _status_after_contention(home, day, before)
        return {
            "folded": False,
            "reason": "lock_contended",
            "fold": {},
            "prune": {},
            "status": status,
        }

    try:
        pruned = footprint_prune(
            store,
            day,
            settings["retention_days"],
            busy_timeout_ms=_BUSY_TIMEOUT_MS,
        )
    except TimeoutError:
        pruned = {"skipped": True, "reason": "lock_contended"}

    if int(folded.get("records_folded", 0)) > 0 and not before.get("first_record_day"):
        _upsert_disclosure_notification()

    status = _status_after_contention(home, day, before)
    return {
        "folded": True,
        "reason": None,
        "fold": folded,
        "prune": pruned,
        "status": status,
    }


def fold_if_stale(
    *,
    max_age: timedelta = _FOLD_MAX_AGE,
    sase_home: Path | None = None,
    today: str | None = None,
) -> dict[str, Any]:
    """Fold pending spool bytes only when the last fold is stale."""
    home = Path(sase_home) if sase_home is not None else default_sase_home()
    day = today or date.today().isoformat()
    try:
        status = _read_status(home, day, _BUSY_TIMEOUT_MS)
    except TimeoutError:
        status = _read_status(home, day, _STATUS_RETRY_TIMEOUT_MS)
    if int(status.get("spool_bytes_pending", 0)) <= 0:
        return status
    last_fold = _parse_timestamp(status.get("last_fold_at"))
    now = datetime.now(UTC)
    if last_fold is not None and now - last_fold < max_age:
        return status
    outcome = fold_ledger(sase_home=home, today=day, initial_status=status)
    return dict(outcome.get("status") or status)


def clear_ledger(*, sase_home: Path | None = None) -> dict[str, Any]:
    """Clear ledger and spool data, then publish the new TUI generation."""
    home = Path(sase_home) if sase_home is not None else default_sase_home()
    result = footprint_clear(
        footprint_ledger_path(home),
        footprint_spool_dir(home),
        busy_timeout_ms=_BUSY_TIMEOUT_MS,
    )
    generation = int(result["generation"])
    _write_generation_file(home, generation)
    return dict(result)


def _read_status(home: Path, day: str, busy_timeout_ms: int) -> dict[str, Any]:
    return footprint_status(
        footprint_ledger_path(home),
        footprint_spool_dir(home),
        day,
        busy_timeout_ms=busy_timeout_ms,
    )


def _status_after_contention(
    home: Path,
    day: str,
    fallback: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        return _read_status(home, day, _STATUS_RETRY_TIMEOUT_MS)
    except TimeoutError:
        return dict(fallback)


def _footprint_settings() -> dict[str, int]:
    from sase.config.core import load_merged_config

    raw = load_merged_config().get("footprint", {})
    section = raw if isinstance(raw, Mapping) else {}
    return {
        key: _config_int(section.get(key), default)
        for key, default in _DEFAULTS.items()
    }


def _config_int(value: Any, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(value, 0)


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _upsert_disclosure_notification() -> None:
    from uuid import uuid4

    from sase.notifications.models import Notification, normalize_notification_tags
    from sase.notifications.store import upsert_notification

    notification = Notification(
        id=str(uuid4()),
        timestamp=datetime.now(UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        sender="footprint",
        icon="◉",
        notes=[
            "Footprint is recording local usage counts (feature IDs only; nothing "
            "leaves this machine). Review it in Admin Center → Statistics → "
            "Footprint · turn off with `sase footprint mode off`."
        ],
        tags=normalize_notification_tags(("footprint", "disclosure")),
        dedup_key="footprint.disclosure",
    )
    try:
        upsert_notification(notification)
    except Exception:  # noqa: BLE001 - disclosure must not break the fold.
        _LOG.warning(
            "Failed to upsert Footprint disclosure notification", exc_info=True
        )


def _write_generation_file(home: Path, generation: int) -> None:
    target = (
        generation_path()
        if home == default_sase_home()
        else home / "footprint" / "generation"
    )
    if "PYTEST_CURRENT_TEST" in os.environ or "PYTEST_VERSION" in os.environ:
        from sase.core.state_write_guard import assert_test_state_write_isolated

        assert_test_state_write_isolated(target, category="Footprint generation")

    directory = target.parent
    os.makedirs(directory, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    fd, temporary = tempfile.mkstemp(prefix=".generation-", dir=directory)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            fd = -1
            stream.write(f"{generation}\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


__all__ = ["clear_ledger", "fold_if_stale", "fold_ledger"]
