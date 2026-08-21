"""Feature-flag env transport tests."""

from __future__ import annotations

import pytest

from sase.feature_flags import FeatureFlagEnvError
from sase.feature_flags import env as env_mod
from sase.feature_flags.env import (
    SASE_FEATURE_FLAGS_ENV,
    _LegacyEnvMapping,
    apply_feature_flags_env,
    collect_legacy_env_values,
    merge_feature_flags_env,
    parse_feature_flags_env,
)
from sase.feature_flags.resolver import resolve_feature_flags

from ._helpers import definitions, demo_flag, layer

_DEMO_DISABLE = _LegacyEnvMapping(
    name="SASE_DISABLE_DEMO",
    key="demo_flag",
    invert=True,
)


def test_collect_legacy_env_values_is_empty_without_mappings() -> None:
    assert collect_legacy_env_values({}) == {}
    assert collect_legacy_env_values({"SASE_DISABLE_PRETTIER": "1"}) == {}
    assert collect_legacy_env_values({"SASE_DISABLE_DEMO": "1"}) == {}


def test_collect_legacy_env_values_inverts_disable_style_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(env_mod, "_LEGACY_ENV_MAPPINGS", (_DEMO_DISABLE,))

    assert collect_legacy_env_values({}) == {}
    assert collect_legacy_env_values({"SASE_DISABLE_DEMO": ""}) == {}
    assert collect_legacy_env_values({"SASE_DISABLE_DEMO": "1"}) == {
        "demo_flag": (False, "SASE_DISABLE_DEMO")
    }
    assert collect_legacy_env_values({"SASE_DISABLE_DEMO": "0"}) == {
        "demo_flag": (False, "SASE_DISABLE_DEMO")
    }


def test_env_round_trips_all_registered_keys_stably() -> None:
    snapshot = resolve_feature_flags(
        definitions=definitions(
            demo_flag("alpha_flag", kind="sunset"),
            demo_flag("demo_flag"),
        ),
        layers=[],
    )

    env: dict[str, str] = {}
    apply_feature_flags_env(snapshot, env)
    encoded = env[SASE_FEATURE_FLAGS_ENV]

    assert encoded == '{"alpha_flag":true,"demo_flag":false}'
    apply_feature_flags_env(snapshot, env)
    assert env[SASE_FEATURE_FLAGS_ENV] == encoded
    assert parse_feature_flags_env(encoded) == {
        "alpha_flag": True,
        "demo_flag": False,
    }


def test_applied_env_pins_child_process_resolution() -> None:
    """Global snapshots still pin child processes; local values cannot override.

    This is why the old sase-o2 reproduction — a scope:"project" flag resolving
    against the wrong project — cannot happen on the current architecture.
    """
    definitions_by_key = definitions(demo_flag())
    parent = resolve_feature_flags(
        definitions=definitions_by_key,
        layers=[layer("user", {"demo_flag": True})],
    )
    env: dict[str, str] = {}

    apply_feature_flags_env(parent, env)
    child = resolve_feature_flags(
        definitions=definitions_by_key,
        layers=[layer("local", {"demo_flag": False})],
        env_value=env[SASE_FEATURE_FLAGS_ENV],
    )

    assert env[SASE_FEATURE_FLAGS_ENV] == '{"demo_flag":true}'
    assert child.enabled("demo_flag") is True
    assert child.decision("demo_flag").source == "env"


def test_merge_feature_flags_env_creates_var_when_unset() -> None:
    env: dict[str, str] = {}

    merge_feature_flags_env({"demo_flag": True}, env)

    assert env[SASE_FEATURE_FLAGS_ENV] == '{"demo_flag":true}'


def test_merge_feature_flags_env_merges_over_inherited_keys() -> None:
    env = {SASE_FEATURE_FLAGS_ENV: '{"alpha_flag":true,"demo_flag":false}'}

    merge_feature_flags_env({"demo_flag": True, "beta_flag": False}, env)

    assert parse_feature_flags_env(env[SASE_FEATURE_FLAGS_ENV]) == {
        "alpha_flag": True,
        "beta_flag": False,
        "demo_flag": True,
    }


def test_merge_feature_flags_env_overwrites_conflicting_inherited_key() -> None:
    env = {SASE_FEATURE_FLAGS_ENV: '{"demo_flag":false}'}

    merge_feature_flags_env({"demo_flag": True}, env)

    assert env[SASE_FEATURE_FLAGS_ENV] == '{"demo_flag":true}'


def test_merge_feature_flags_env_leaves_unrelated_keys_alone() -> None:
    env = {SASE_FEATURE_FLAGS_ENV: '{"keep_me":true}'}

    merge_feature_flags_env({"demo_flag": False}, env)

    assert parse_feature_flags_env(env[SASE_FEATURE_FLAGS_ENV]) == {
        "demo_flag": False,
        "keep_me": True,
    }


def test_merge_feature_flags_env_raises_on_malformed_inherited_value() -> None:
    env = {SASE_FEATURE_FLAGS_ENV: "not-json"}

    with pytest.raises(FeatureFlagEnvError):
        merge_feature_flags_env({"demo_flag": True}, env)
