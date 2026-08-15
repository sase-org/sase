"""Load-balanced model-alias state and availability tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.llm_provider import config as llm_config
from sase.llm_provider.config import resolve_model_alias
from tests.llm_provider._load_balanced_alias_helpers import (
    configure_pool,
    pool_member_snapshot,
)
from tests.llm_provider._provider_config_helpers import mock_provider_config


def test_pool_member_snapshot_marks_fresh_and_advanced_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_pool(monkeypatch)

    assert [member.selected for member in pool_member_snapshot()] == [
        True,
        False,
    ]
    resolve_model_alias("@pool", consume=True)
    assert [member.selected for member in pool_member_snapshot()] == [
        False,
        True,
    ]


def test_pool_member_snapshot_marks_available_skip_and_all_down_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_pool(monkeypatch)
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda target: target.startswith("codex/"),
    )

    members = pool_member_snapshot()
    assert [member.available for member in members] == [False, True]
    assert [member.selected for member in members] == [False, True]

    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: False,
    )
    members = pool_member_snapshot()
    assert [member.available for member in members] == [False, False]
    assert [member.selected for member in members] == [True, False]


def test_pool_member_snapshot_resets_next_marker_after_membership_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg: dict[str, object] = {
        "provider": "claude",
        "model_aliases": {
            "custom": {
                "pool": {
                    "model": "claude/opus | codex/o3",
                    "description": "Test pool.",
                }
            }
        },
    }
    mock_provider_config(monkeypatch, cfg)
    monkeypatch.setattr(
        llm_config,
        "_resolved_target_is_available",
        lambda _target: True,
    )
    resolve_model_alias("@pool", consume=True)
    assert [member.selected for member in pool_member_snapshot()] == [
        False,
        True,
    ]

    cfg["model_aliases"] = {
        "custom": {
            "pool": {
                "model": "codex/gpt-5.5 | claude/sonnet",
                "description": "Test pool.",
            }
        }
    }
    llm_config._get_model_aliases_for_token.cache_clear()
    assert [member.selected for member in pool_member_snapshot()] == [
        True,
        False,
    ]


def test_corrupt_or_locked_state_never_crashes_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_pool(monkeypatch)
    state_path = Path.home() / ".sase" / "llm_lb.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("{not-json", encoding="utf-8")
    assert resolve_model_alias("@pool", consume=True) == "claude/opus"

    from sase.llm_provider import load_balancing

    monkeypatch.setattr(
        load_balancing,
        "_locked_state",
        MagicMock(side_effect=OSError("lock unavailable")),
    )
    assert resolve_model_alias("@pool", consume=True) == "claude/opus"


def test_rotation_state_records_alias_fingerprint_and_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_pool(monkeypatch)
    resolve_model_alias("@pool", consume=True)
    state_path = Path.home() / ".sase" / "llm_lb.json"
    data = json.loads(state_path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["entries"]["pool"]["alias"] == "pool"
    assert data["entries"]["pool"]["cursor"] == 1
    assert len(data["entries"]["pool"]["fingerprint"]) == 64


def test_provider_availability_probe_is_cached_and_honors_path_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.llm_provider import registry

    monkeypatch.setattr(
        registry,
        "_llm_metadata_payload",
        lambda: {"providers": {"codex": {"autodetect_cli_name": "codex"}}},
    )
    monkeypatch.setenv("SASE_CODEX_PATH", "/opt/codex/bin/codex")
    which = MagicMock(return_value="/opt/codex/bin/codex")
    monkeypatch.setattr(registry.shutil, "which", which)
    registry._provider_cli_available.cache_clear()

    assert registry._provider_cli_available("codex") is True
    assert registry._provider_cli_available("codex") is True
    which.assert_called_once_with("/opt/codex/bin/codex")
