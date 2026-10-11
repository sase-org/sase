"""Durable onboarding preferences beside the ownership journals."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home

PREFERENCES_SCHEMA_VERSION = 1


@dataclass
class Preferences:
    """Last-used onboarding selections driving wizard defaults."""

    last_provider: str = ""
    last_owner: dict[str, str] = field(default_factory=dict)
    last_visibility: dict[str, str] = field(default_factory=dict)


def preferences_path() -> Path:
    """Return the onboarding ``preferences.json`` path under ``$SASE_HOME``."""

    return sase_home() / "project_onboarding" / "preferences.json"


def load_preferences() -> Preferences:
    """Load onboarding preferences, tolerating a missing or corrupt file."""

    try:
        raw = json.loads(preferences_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Preferences()
    if not isinstance(raw, dict):
        return Preferences()
    last_owner = raw.get("last_owner")
    last_visibility = raw.get("last_visibility")
    return Preferences(
        last_provider=(
            str(raw.get("last_provider") or "")
            if isinstance(raw.get("last_provider"), str)
            else ""
        ),
        last_owner=(
            {str(k): str(v) for k, v in last_owner.items()}
            if isinstance(last_owner, dict)
            else {}
        ),
        last_visibility=(
            {str(k): str(v) for k, v in last_visibility.items()}
            if isinstance(last_visibility, dict)
            else {}
        ),
    )


def save_preferences(prefs: Preferences) -> None:
    """Persist *prefs* atomically, creating the parent directory as needed."""

    path = preferences_path()
    payload: dict[str, Any] = {
        "schema_version": PREFERENCES_SCHEMA_VERSION,
        **asdict(prefs),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def record_provider_selection(workflow_type: str) -> Preferences:
    """Remember *workflow_type* as the last-used provider and return the prefs."""

    prefs = load_preferences()
    prefs.last_provider = workflow_type
    save_preferences(prefs)
    return prefs


def record_owner_selection(workflow_type: str, owner: str) -> Preferences:
    """Remember *owner* as the last-used namespace for *workflow_type*."""

    prefs = load_preferences()
    prefs.last_owner[workflow_type] = owner
    save_preferences(prefs)
    return prefs


def record_visibility_selection(owner: str, visibility: str) -> Preferences:
    """Remember *visibility* as the last choice for *owner*."""

    prefs = load_preferences()
    prefs.last_visibility[owner] = visibility
    save_preferences(prefs)
    return prefs


__all__ = [
    "PREFERENCES_SCHEMA_VERSION",
    "Preferences",
    "load_preferences",
    "preferences_path",
    "record_owner_selection",
    "record_provider_selection",
    "record_visibility_selection",
    "save_preferences",
]
