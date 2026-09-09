"""Both-states coverage for registered consumer feature flags."""

from __future__ import annotations

import pytest

from sase.feature_flags import FeatureFlag, current_flags, override_flags
from sase.feature_flags.registry import feature_flag_definitions
from sase.feature_flags.resolver import resolve_feature_flags

from ._helpers import layer


def test_registered_consumer_flags_have_expected_kinds() -> None:
    definitions = feature_flag_definitions()

    flags_pane = definitions[FeatureFlag.admin_center_flags]
    ref_sync = definitions[FeatureFlag.ref_sync_gesture]
    typed_launch = definitions[FeatureFlag.typed_launch_units]
    refresh_tokens = definitions[FeatureFlag.ace_refresh_tokens]

    assert flags_pane.kind == "sunset"
    assert flags_pane.default is True
    assert flags_pane.bead == "sase-rx"
    assert refresh_tokens.kind == "sunset"
    assert refresh_tokens.default is True
    assert refresh_tokens.bead == "sase-wr"
    assert ref_sync.kind == "sunset"
    assert ref_sync.default is True
    assert ref_sync.bead == "sase-qu"
    assert typed_launch.kind == "beta"
    assert typed_launch.default is False
    assert typed_launch.bead == "sase-s7"


def test_consumer_flags_resolve_from_every_layer() -> None:
    definitions = feature_flag_definitions()

    default = resolve_feature_flags(definitions=definitions, layers=[])
    assert default.enabled(FeatureFlag.admin_center_flags) is True
    assert default.enabled(FeatureFlag.ref_sync_gesture) is True
    assert default.enabled(FeatureFlag.ace_refresh_tokens) is True
    assert default.enabled(FeatureFlag.typed_launch_units) is False

    user = resolve_feature_flags(
        definitions=definitions,
        layers=[
            layer(
                "user",
                {
                    "admin_center_flags": False,
                    "ref_sync_gesture": False,
                    "ace_refresh_tokens": False,
                    "typed_launch_units": True,
                },
                detail="user.yml",
            )
        ],
    )
    assert user.enabled(FeatureFlag.admin_center_flags) is False
    assert user.decision(FeatureFlag.admin_center_flags).source == "user"
    assert user.enabled(FeatureFlag.ref_sync_gesture) is False
    assert user.decision(FeatureFlag.ref_sync_gesture).source == "user"
    assert user.enabled(FeatureFlag.ace_refresh_tokens) is False
    assert user.decision(FeatureFlag.ace_refresh_tokens).source == "user"
    assert user.enabled(FeatureFlag.typed_launch_units) is True
    assert user.decision(FeatureFlag.typed_launch_units).source == "user"

    env = resolve_feature_flags(
        definitions=definitions,
        layers=[],
        env_value=(
            '{"admin_center_flags":false,"ref_sync_gesture":false,'
            '"ace_refresh_tokens":false,"typed_launch_units":true}'
        ),
    )
    assert env.enabled(FeatureFlag.admin_center_flags) is False
    assert env.decision(FeatureFlag.admin_center_flags).source == "env"
    assert env.enabled(FeatureFlag.ref_sync_gesture) is False
    assert env.decision(FeatureFlag.ref_sync_gesture).source == "env"
    assert env.enabled(FeatureFlag.ace_refresh_tokens) is False
    assert env.decision(FeatureFlag.ace_refresh_tokens).source == "env"
    assert env.enabled(FeatureFlag.typed_launch_units) is True
    assert env.decision(FeatureFlag.typed_launch_units).source == "env"


def test_consumer_flags_both_states_via_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_FEATURE_FLAGS", raising=False)
    with override_flags(
        admin_center_flags=False,
        ref_sync_gesture=False,
        ace_refresh_tokens=False,
        typed_launch_units=True,
    ) as snapshot:
        assert snapshot.enabled(FeatureFlag.admin_center_flags) is False
        assert current_flags().enabled(FeatureFlag.admin_center_flags) is False
        assert snapshot.enabled(FeatureFlag.ref_sync_gesture) is False
        assert current_flags().enabled(FeatureFlag.ref_sync_gesture) is False
        assert snapshot.enabled(FeatureFlag.ace_refresh_tokens) is False
        assert current_flags().enabled(FeatureFlag.ace_refresh_tokens) is False
        assert snapshot.enabled(FeatureFlag.typed_launch_units) is True
        assert current_flags().enabled(FeatureFlag.typed_launch_units) is True

    restored = current_flags()
    assert restored.enabled(FeatureFlag.admin_center_flags) is True
    assert restored.enabled(FeatureFlag.ref_sync_gesture) is True
    assert restored.enabled(FeatureFlag.ace_refresh_tokens) is True
    assert restored.enabled(FeatureFlag.typed_launch_units) is False
