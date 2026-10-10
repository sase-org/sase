"""Both-states coverage for generic beta/sunset flag resolution.

These tests deliberately use synthetic ``demo_*`` definitions instead of
production rollout keys so later flag-retirement phases can delete registry
members without breaking generic framework assumptions.
"""

from __future__ import annotations

import pytest

from sase.feature_flags import current_flags, override_flags
from sase.feature_flags import snapshot as snapshot_mod
from sase.feature_flags.resolver import resolve_feature_flags
from tests._conftest_runtime import reset_process_feature_flags

from ._helpers import definitions, demo_flag, layer


BETA_KEY = "demo_beta_flag"
SUNSET_KEY = "demo_sunset_flag"


@pytest.fixture(autouse=True)
def _synthetic_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve the process snapshot from synthetic defs, never live keys."""
    test_definitions = definitions(
        demo_flag(BETA_KEY, kind="beta"),
        demo_flag(SUNSET_KEY, kind="sunset"),
    )
    monkeypatch.setattr(
        "sase.feature_flags.registry.feature_flag_definitions",
        lambda: test_definitions,
    )
    monkeypatch.setattr(
        snapshot_mod, "feature_flag_definitions", lambda: test_definitions
    )
    monkeypatch.setattr(snapshot_mod, "_project_layer_inputs", lambda: ((), ()))
    monkeypatch.setattr(snapshot_mod, "_saved_state_input", lambda: ({}, (), ""))
    monkeypatch.delenv("SASE_FEATURE_FLAGS", raising=False)
    reset_process_feature_flags()


def test_synthetic_beta_and_sunset_flags_have_expected_kinds() -> None:
    beta = demo_flag(BETA_KEY, kind="beta")
    sunset = demo_flag(SUNSET_KEY, kind="sunset")

    assert beta.kind == "beta"
    assert beta.default is False
    assert beta.bead == "sase-nb.test"
    assert sunset.kind == "sunset"
    assert sunset.default is True
    assert sunset.bead == "sase-nb.test"


def test_synthetic_flags_resolve_from_every_layer() -> None:
    synthetic = definitions(
        demo_flag(BETA_KEY, kind="beta"),
        demo_flag(SUNSET_KEY, kind="sunset"),
    )

    default = resolve_feature_flags(definitions=synthetic, layers=[])
    assert default.enabled(BETA_KEY) is False
    assert default.enabled(SUNSET_KEY) is True

    user = resolve_feature_flags(
        definitions=synthetic,
        layers=[
            layer(
                "user",
                {BETA_KEY: True, SUNSET_KEY: False},
                detail="user.yml",
            )
        ],
    )
    assert user.enabled(BETA_KEY) is True
    assert user.decision(BETA_KEY).source == "user"
    assert user.enabled(SUNSET_KEY) is False
    assert user.decision(SUNSET_KEY).source == "user"

    env = resolve_feature_flags(
        definitions=synthetic,
        layers=[],
        env_value='{"demo_beta_flag":true,"demo_sunset_flag":false}',
    )
    assert env.enabled(BETA_KEY) is True
    assert env.decision(BETA_KEY).source == "env"
    assert env.enabled(SUNSET_KEY) is False
    assert env.decision(SUNSET_KEY).source == "env"


def test_synthetic_flags_both_states_via_override() -> None:
    with override_flags(
        demo_beta_flag=True,
        demo_sunset_flag=False,
    ) as snapshot:
        assert snapshot.enabled(BETA_KEY) is True
        assert current_flags().enabled(BETA_KEY) is True
        assert snapshot.enabled(SUNSET_KEY) is False
        assert current_flags().enabled(SUNSET_KEY) is False

    restored = current_flags()
    assert restored.enabled(BETA_KEY) is False
    assert restored.enabled(SUNSET_KEY) is True
