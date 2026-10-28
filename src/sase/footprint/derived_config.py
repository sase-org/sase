"""User config override snapshot as Footprint ``derived.config`` rows."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.config.core import CONFIG_DIR
from sase.config.loading import get_overlay_paths, load_yaml_file
from sase.footprint.derived_rows import coverage_row, daily_row
from sase.footprint.ids import custom_id, sanitize

ORIGIN = "derived.config"
_SURFACE = "config"
_ACTOR = "human"
_VIA = "config"


def extract_config_rows(
    *,
    catalog_ids: set[str],
    today: str,
    config_dir: Path | None = None,
) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return today's override snapshot as ``(days, rows, coverage)``.

    Paths only: values from the user YAML are never copied onto a row.
    Unknown user keys collapse to ``config:~custom``.
    """
    directory = Path(config_dir) if config_dir is not None else CONFIG_DIR
    known: set[str] = set()
    unknown = 0
    for mapping in _user_mappings(directory):
        for path in _leaf_paths(mapping):
            feature_id = f"config:{path}"
            if feature_id in catalog_ids:
                known.add(feature_id)
            else:
                unknown += 1

    rows = [
        daily_row(today, feature_id, actor=_ACTOR, via=_VIA, n=1)
        for feature_id in sorted(known)
    ]
    if unknown:
        rows.append(
            daily_row(today, custom_id("config"), actor=_ACTOR, via=_VIA, n=unknown)
        )
    records = len(known) + unknown
    coverage = [
        coverage_row(
            today,
            _SURFACE,
            records=records,
            human_active=1 if records else 0,
            unknown_ids=int(bool(unknown)),
        )
    ]
    return [today], rows, coverage


def _user_mappings(config_dir: Path) -> list[Mapping[str, Any]]:
    mappings: list[Mapping[str, Any]] = []
    for path in [config_dir / "sase.yml", *get_overlay_paths(config_dir)]:
        data = load_yaml_file(path)
        if isinstance(data, dict):
            mappings.append(data)
    return mappings


def _leaf_paths(node: Mapping[str, Any], prefix: str = "") -> list[str]:
    out: list[str] = []
    for key in node:
        if prefix == "" and key == "footprint":
            continue
        segment = sanitize(str(key))
        path = f"{prefix}.{segment}" if prefix else segment
        value = node[key]
        if isinstance(value, dict) and value:
            out.extend(_leaf_paths(value, path))
        else:
            out.append(path)
    return out


__all__ = ["ORIGIN", "extract_config_rows"]
