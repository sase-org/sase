"""Shared fixtures and builders for common-placeholder store tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import sase.history.prompt_placeholders as store
from sase.history.prompt_store import PromptEntry
from tests.conftest import redirect_sase_home


def make_sase_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Sandbox ``~/.sase`` and default the placeholder limit to 100.

    Each test module wraps this in its own ``sase_home_dir`` fixture; importing
    a fixture across modules trips ruff's redefinition check.
    """
    home = redirect_sase_home(monkeypatch, tmp_path / ".sase")
    set_limit(monkeypatch, 100)
    return home


def set_limit(monkeypatch: pytest.MonkeyPatch, limit: int) -> None:
    """Point ``_common_placeholder_limit`` at a fixed configured value."""
    monkeypatch.setattr(
        store,
        "load_merged_config",
        lambda: {"ace": {"prompt_completion": {"common_placeholder_count": limit}}},
    )


def freeze_timestamps(
    monkeypatch: pytest.MonkeyPatch,
    timestamps: list[str],
) -> None:
    """Serve *timestamps* in order, repeating the last one when exhausted."""
    pending = list(timestamps)

    def _next() -> str:
        return pending.pop(0) if len(pending) > 1 else pending[0]

    monkeypatch.setattr(store, "generate_timestamp", _next)


def store_file(home: Path) -> Path:
    return home / "prompt_placeholders.json"


def read_store(home: Path) -> dict[str, Any]:
    return json.loads(store_file(home).read_text(encoding="utf-8"))


def core_entries(home: Path) -> list[dict[str, Any]]:
    """Return the version-1 placeholder fields, ignoring context bags."""
    return [
        {"text": item["text"], "count": item["count"], "last_used": item["last_used"]}
        for item in read_store(home)["placeholders"]
    ]


def write_store(home: Path, payload: dict[str, Any]) -> None:
    store_file(home).write_text(json.dumps(payload), encoding="utf-8")


def version_1_store(*placeholders: dict[str, Any]) -> dict[str, Any]:
    return {"version": 1, "placeholders": list(placeholders)}


def entry(text: str, last_used: str) -> PromptEntry:
    return PromptEntry(text=text, timestamp=last_used, last_used=last_used)
