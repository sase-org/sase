"""Query builder for ``sase footprint list/show/decide``.

Off-hot-path helpers that turn CLI flags into sase-core ``footprint_report``,
``footprint_card``, and ``footprint_decide`` requests. The Rust ledger owns
validation, aggregation, and the candidate gate; this module only resolves
paths, the curated overlay, gate thresholds from config, and the ``--range``
window.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

from sase.core.footprint_facade import (
    footprint_card,
    footprint_decide,
    footprint_report,
)
from sase.footprint.catalog import Overlay, load_overlay
from sase.footprint.constants import (
    ACTOR_SCOPES,
    DECISIONS,
    FORMATS,
    KEEP_REASONS,
    LENSES,
)

_DEFAULT_REVIEW = {
    "min_catalog_days": 60,
    "min_active_days": 30,
    "calibration_days": 3,
    "fading_days": 30,
}


def parse_range_days(value: str | None) -> int | None:
    """Parse a ``--range`` value into window days (``None`` means all)."""
    if value is None:
        return 60
    text = value.strip().lower()
    if text == "all":
        return None
    if text.endswith("d"):
        number = text[:-1]
        days = _parse_positive_int(number, value)
        return days
    if text.endswith("w"):
        number = text[:-1]
        weeks = _parse_positive_int(number, value)
        return weeks * 7
    raise ValueError(
        f"invalid range {value!r}: expected Nd, Nw, or all (for example 60d)"
    )


def _parse_positive_int(number: str, original: str) -> int:
    try:
        parsed = int(number)
    except ValueError:
        raise ValueError(
            f"invalid range {original!r}: expected Nd, Nw, or all (for example 60d)"
        ) from None
    if parsed <= 0:
        raise ValueError(
            f"invalid range {original!r}: expected Nd, Nw, or all (for example 60d)"
        )
    return parsed


def review_settings() -> dict[str, int]:
    """Return gate thresholds from config with wire defaults."""
    from sase.config.core import load_merged_config

    raw = load_merged_config().get("footprint", {})
    section = raw if isinstance(raw, Mapping) else {}
    review = section.get("review", {})
    review_map = review if isinstance(review, Mapping) else {}
    settings: dict[str, int] = {}
    for key, default in _DEFAULT_REVIEW.items():
        settings[key] = _config_int(review_map.get(key), default)
    return settings


def _config_int(value: Any, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(value, 0)


def overlay_payload(path: Path | None = None) -> dict[str, Any]:
    """Return the curated overlay as JSON for the Rust query wire."""
    overlay: Overlay = load_overlay(path)
    return {
        "schema": overlay.schema,
        "features": dict(overlay.features),
        "retire_with": [list(group) for group in overlay.retire_with],
    }


def build_report_request(
    *,
    lens: str = "map",
    actor: str = "you",
    window_days: int | None = 60,
    area: str | None = None,
    store_path: Path | str | None = None,
    today: str | None = None,
    overlay: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a ``footprint_report`` request dict."""
    from sase.footprint.paths import ledger_path

    settings = review_settings()
    request: dict[str, Any] = {
        "store_path": str(store_path) if store_path is not None else str(ledger_path()),
        "today": today or date.today().isoformat(),
        "lens": lens,
        "actor": actor,
        "overlay": dict(overlay) if overlay is not None else overlay_payload(),
        "min_catalog_days": settings["min_catalog_days"],
        "min_active_days": settings["min_active_days"],
        "calibration_days": settings["calibration_days"],
        "fading_days": settings["fading_days"],
    }
    if window_days is None:
        request["window_days"] = None
    else:
        request["window_days"] = int(window_days)
    if area is not None:
        request["area"] = area
    return request


def build_card_request(
    *,
    target: str,
    actor: str = "you",
    window_days: int | None = 60,
    store_path: Path | str | None = None,
    today: str | None = None,
    overlay: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a ``footprint_card`` request for a feature ID or area."""
    from sase.footprint.paths import ledger_path

    settings = review_settings()
    request: dict[str, Any] = {
        "store_path": str(store_path) if store_path is not None else str(ledger_path()),
        "today": today or date.today().isoformat(),
        "actor": actor,
        "lens": "map",
        "overlay": dict(overlay) if overlay is not None else overlay_payload(),
        "min_catalog_days": settings["min_catalog_days"],
        "min_active_days": settings["min_active_days"],
        "calibration_days": settings["calibration_days"],
        "fading_days": settings["fading_days"],
    }
    if window_days is None:
        request["window_days"] = None
    else:
        request["window_days"] = int(window_days)
    if ":" in target:
        request["feature_id"] = target
    else:
        request["area"] = target
    return request


def fetch_report(request: Mapping[str, Any]) -> dict[str, Any]:
    """Run ``footprint_report`` for an already-built request."""
    return dict(footprint_report(dict(request)))


def fetch_card(request: Mapping[str, Any]) -> dict[str, Any]:
    """Run ``footprint_card`` for an already-built request."""
    return dict(footprint_card(dict(request)))


def record_decision(
    feature_id: str,
    decision: str,
    reason: str | None,
    *,
    store_path: Path | str | None = None,
    today: str | None = None,
) -> dict[str, Any]:
    """Record, snooze, or clear a local review decision."""
    from sase.footprint.paths import ledger_path

    store = str(store_path) if store_path is not None else str(ledger_path())
    day = today or date.today().isoformat()
    return dict(
        footprint_decide(store, feature_id, decision, reason, day),
    )


__all__ = [
    "ACTOR_SCOPES",
    "DECISIONS",
    "FORMATS",
    "KEEP_REASONS",
    "LENSES",
    "build_card_request",
    "build_report_request",
    "fetch_card",
    "fetch_report",
    "overlay_payload",
    "parse_range_days",
    "record_decision",
    "review_settings",
]
