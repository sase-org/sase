"""Machine-local feature-flag state adapter and mutation facade tests."""

from __future__ import annotations

import json
import os
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from sase.core.paths import sase_home
from sase.feature_flags.env import SASE_FEATURE_FLAGS_ENV, parse_feature_flags_env
from sase.feature_flags.models import (
    FeatureFlagError,
    FeatureFlagStateError,
)
from sase.feature_flags.resolver import resolve_feature_flags
from sase.feature_flags.state import (
    FEATURE_FLAG_STATE_FILENAME,
    FEATURE_FLAG_STATE_WIRE_SCHEMA_VERSION,
    feature_flag_state_path,
    load_saved_feature_flags,
    set_saved_feature_flag,
)
from sase.feature_flags import snapshot as snapshot_mod
from tests._conftest_runtime import reset_process_feature_flags

from ._helpers import definitions, demo_flag, layer


BETA_KEY = "epic_resume_gate"
SUNSET_KEY = "prettier_enabled"


@pytest.fixture(autouse=True)
def _registered_test_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep state-facade coverage independent of the live flag lifecycle."""

    test_definitions = definitions(
        demo_flag(BETA_KEY),
        demo_flag(SUNSET_KEY, kind="sunset"),
    )
    monkeypatch.setattr(
        "sase.feature_flags.registry.feature_flag_definitions",
        lambda: test_definitions,
    )
    monkeypatch.setattr(
        snapshot_mod, "feature_flag_definitions", lambda: test_definitions
    )


def _state_file() -> Path:
    return Path(feature_flag_state_path())


def _write_state(flags: dict[str, bool]) -> Path:
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"version": FEATURE_FLAG_STATE_WIRE_SCHEMA_VERSION, "flags": flags},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _file_fingerprint(path: Path) -> tuple[bytes, int]:
    return path.read_bytes(), path.stat().st_mtime_ns


def test_missing_state_is_empty_and_uses_redirected_sase_home() -> None:
    reset_process_feature_flags()
    loaded = load_saved_feature_flags()

    assert Path(loaded.path) == sase_home() / FEATURE_FLAG_STATE_FILENAME
    assert dict(loaded.flags) == {}
    assert loaded.diagnostics == ()
    assert loaded.version == FEATURE_FLAG_STATE_WIRE_SCHEMA_VERSION
    assert not _state_file().exists()


def test_load_round_trips_registered_and_unknown_keys() -> None:
    _write_state({BETA_KEY: True, "future_release_flag": False})
    reset_process_feature_flags()

    loaded = load_saved_feature_flags()
    snapshot = snapshot_mod.current_flags()

    assert dict(loaded.flags) == {BETA_KEY: True, "future_release_flag": False}
    assert snapshot.enabled(BETA_KEY) is True
    assert snapshot.decision(BETA_KEY).source == "state"
    assert "future_release_flag" not in snapshot.decisions
    assert snapshot.saved["future_release_flag"] is False
    assert [item.code for item in snapshot.diagnostics] == ["unknown_key"]
    with pytest.raises(TypeError):
        loaded.flags["future_release_flag"] = True  # type: ignore[index]


def test_corrupt_state_is_non_destructive_and_blocks_mutation() -> None:
    path = _state_file()
    path.write_text("{not-json", encoding="utf-8")
    original = path.read_bytes()
    reset_process_feature_flags()

    loaded = load_saved_feature_flags()
    snapshot = snapshot_mod.current_flags()

    assert dict(loaded.flags) == {}
    assert loaded.diagnostics
    assert loaded.diagnostics[0].code == "malformed_json"
    assert loaded.diagnostics[0].source == "state"
    assert snapshot.decision(BETA_KEY).source == "default"
    assert any(item.code == "malformed_json" for item in snapshot.diagnostics)
    with pytest.raises(FeatureFlagStateError, match="cannot update"):
        set_saved_feature_flag(BETA_KEY, True)
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    ("key", "enabled"),
    [
        (BETA_KEY, True),
        (SUNSET_KEY, False),
    ],
)
def test_mutation_persists_both_kinds_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch, key: str, enabled: bool
) -> None:
    reset_process_feature_flags()
    monkeypatch.delenv(SASE_FEATURE_FLAGS_ENV, raising=False)

    first = set_saved_feature_flag(key, enabled)
    second = set_saved_feature_flag(key, enabled)

    assert first.changed is True
    assert first.previous_saved is None
    assert first.enabled is enabled
    assert first.after.enabled is enabled
    assert first.shadowed is False
    assert first.shadowing_source is None
    assert Path(first.state_path) == _state_file()
    assert second.changed is False
    assert second.previous_saved is enabled
    with pytest.raises(FrozenInstanceError):
        first.changed = False  # type: ignore[misc]


def test_mutation_preserves_unrelated_keys_and_leaves_config_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reset_process_feature_flags()
    monkeypatch.delenv(SASE_FEATURE_FLAGS_ENV, raising=False)
    _write_state({"future_release_flag": True, SUNSET_KEY: False})
    user = tmp_path / "user.yml"
    overlay = tmp_path / "overlay.yml"
    local = tmp_path / "project" / "sase.yml"
    local.parent.mkdir(parents=True, exist_ok=True)
    user.write_text("feature_flags:\n  epic_resume_gate: false\n", encoding="utf-8")
    overlay.write_text("feature_flags:\n  prettier_enabled: true\n", encoding="utf-8")
    local.write_text("feature_flags:\n  epic_resume_gate: true\n", encoding="utf-8")
    fingerprints = {
        path: _file_fingerprint(path) for path in (user, overlay, local, _state_file())
    }
    previous_state = fingerprints[_state_file()]

    outcome = set_saved_feature_flag(BETA_KEY, True)

    assert outcome.changed is True
    loaded = load_saved_feature_flags()
    assert dict(loaded.flags) == {
        BETA_KEY: True,
        SUNSET_KEY: False,
        "future_release_flag": True,
    }
    for path in (user, overlay, local):
        assert _file_fingerprint(path) == fingerprints[path]
    assert _state_file().read_bytes() != previous_state[0]


def test_env_merge_makes_exec_rebuild_see_saved_value_while_cli_still_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_process_feature_flags()
    monkeypatch.delenv(SASE_FEATURE_FLAGS_ENV, raising=False)

    outcome = set_saved_feature_flag(BETA_KEY, True)

    assert outcome.after.enabled is True
    assert parse_feature_flags_env(os.environ[SASE_FEATURE_FLAGS_ENV])[BETA_KEY] is True

    snapshot_mod._snapshot = None
    inherited = snapshot_mod.current_flags()
    assert inherited.enabled(BETA_KEY) is True

    child = resolve_feature_flags(
        definitions=definitions(demo_flag(BETA_KEY)),
        layers=[layer("user", {BETA_KEY: False}, detail="user.yml")],
        saved={BETA_KEY: True},
        saved_detail=feature_flag_state_path(),
        env_value=os.environ[SASE_FEATURE_FLAGS_ENV],
        cli={BETA_KEY: False},
    )
    assert child.enabled(BETA_KEY) is False
    assert child.decision(BETA_KEY).source == "cli"


def test_cli_override_is_recorded_as_shadowing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_process_feature_flags()
    monkeypatch.delenv(SASE_FEATURE_FLAGS_ENV, raising=False)
    snapshot_mod.set_cli_feature_flags({BETA_KEY: False})

    outcome = set_saved_feature_flag(BETA_KEY, True)

    assert outcome.enabled is True
    assert outcome.after.enabled is False
    assert outcome.after.source == "cli"
    assert outcome.shadowed is True
    assert outcome.shadowing_source == "cli"
    loaded = load_saved_feature_flags()
    assert loaded.flags[BETA_KEY] is True


def test_unknown_and_invalid_keys_never_write() -> None:
    reset_process_feature_flags()
    with pytest.raises(FeatureFlagError, match="unknown feature flag"):
        set_saved_feature_flag("not_a_registered_flag", True)
    with pytest.raises(FeatureFlagError, match="snake_case"):
        set_saved_feature_flag("NotSnake", True)
    with pytest.raises(FeatureFlagError, match="must be boolean"):
        set_saved_feature_flag(BETA_KEY, 1)  # type: ignore[arg-type]
    assert not _state_file().exists()


def test_binding_failure_includes_state_path(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_name: str) -> Any:
        raise RuntimeError("wheel exploded")

    monkeypatch.setattr(
        "sase.feature_flags.state.require_rust_binding",
        boom,
    )
    path = feature_flag_state_path()

    with pytest.raises(FeatureFlagStateError, match="wheel exploded") as captured:
        load_saved_feature_flags()

    assert captured.value.path == path
    assert path in str(captured.value)


def test_stale_wire_version_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_require(name: str) -> Any:
        def get(_home: str) -> dict[str, Any]:
            return {
                "version": 99,
                "flags": {},
                "path": feature_flag_state_path(),
                "diagnostics": [],
            }

        def set_flag(_home: str, _flag: str, _enabled: bool) -> dict[str, Any]:
            return get(_home)

        return get if name.endswith("_get") else set_flag

    monkeypatch.setattr(
        "sase.feature_flags.state.require_rust_binding",
        fake_require,
    )

    with pytest.raises(FeatureFlagStateError, match="unsupported"):
        load_saved_feature_flags()


def test_extra_wire_fields_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_require(_name: str) -> Any:
        def get(_home: str) -> dict[str, Any]:
            return {
                "version": 1,
                "flags": {},
                "path": feature_flag_state_path(),
                "diagnostics": [],
                "extra": True,
            }

        return get

    monkeypatch.setattr(
        "sase.feature_flags.state.require_rust_binding",
        fake_require,
    )

    with pytest.raises(FeatureFlagStateError, match="unknown extra"):
        load_saved_feature_flags()
