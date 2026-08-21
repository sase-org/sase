"""Both-states coverage for registered consumer feature flags."""

from __future__ import annotations

import pytest

from sase.feature_flags import FeatureFlag, current_flags, override_flags
from sase.feature_flags.registry import feature_flag_definitions
from sase.feature_flags.resolver import resolve_feature_flags

from ._helpers import layer


def test_registered_consumer_flags_have_expected_kinds() -> None:
    definitions = feature_flag_definitions()

    ref_sync = definitions[FeatureFlag.ref_sync_gesture]

    assert ref_sync.kind == "sunset"
    assert ref_sync.default is True
    assert ref_sync.bead == "sase-qu"


def test_consumer_flags_resolve_from_every_layer() -> None:
    definitions = feature_flag_definitions()

    default = resolve_feature_flags(definitions=definitions, layers=[])
    assert default.enabled(FeatureFlag.ref_sync_gesture) is True

    user = resolve_feature_flags(
        definitions=definitions,
        layers=[
            layer(
                "user",
                {
                    "ref_sync_gesture": False,
                },
                detail="user.yml",
            )
        ],
    )
    assert user.enabled(FeatureFlag.ref_sync_gesture) is False
    assert user.decision(FeatureFlag.ref_sync_gesture).source == "user"

    env = resolve_feature_flags(
        definitions=definitions,
        layers=[],
        env_value='{"ref_sync_gesture":false}',
    )
    assert env.enabled(FeatureFlag.ref_sync_gesture) is False
    assert env.decision(FeatureFlag.ref_sync_gesture).source == "env"


def test_consumer_flags_both_states_via_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_FEATURE_FLAGS", raising=False)
    with override_flags(
        ref_sync_gesture=False,
    ) as snapshot:
        assert snapshot.enabled(FeatureFlag.ref_sync_gesture) is False
        assert current_flags().enabled(FeatureFlag.ref_sync_gesture) is False

    restored = current_flags()
    assert restored.enabled(FeatureFlag.ref_sync_gesture) is True
