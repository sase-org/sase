"""Feature-flag env transport tests."""

from __future__ import annotations

from sase.feature_flags.env import (
    SASE_FEATURE_FLAGS_ENV,
    apply_feature_flags_env,
    encode_feature_flags_env,
    parse_feature_flags_env,
)
from sase.feature_flags.resolver import resolve_feature_flags

from ._helpers import definitions, demo_flag, layer


def test_env_round_trips_all_registered_keys_stably() -> None:
    snapshot = resolve_feature_flags(
        definitions=definitions(
            demo_flag("alpha_flag", default=True),
            demo_flag("demo_flag", default=False),
        ),
        layers=[],
    )

    encoded = encode_feature_flags_env(snapshot)

    assert encoded == '{"alpha_flag":true,"demo_flag":false}'
    assert encode_feature_flags_env(snapshot) == encoded
    assert parse_feature_flags_env(encoded) == {
        "alpha_flag": True,
        "demo_flag": False,
    }


def test_applied_env_pins_child_process_resolution() -> None:
    definitions_by_key = definitions(demo_flag(default=False))
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
