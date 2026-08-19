"""Both-states coverage for the first two registered feature flags."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sase.feature_flags import FeatureFlag, current_flags, override_flags
from sase.feature_flags.registry import feature_flag_definitions
from sase.feature_flags.resolver import resolve_feature_flags
from sase.file_references import format_with_prettier

from ._helpers import layer


def test_registered_consumer_flags_have_expected_kinds() -> None:
    definitions = feature_flag_definitions()

    coder = definitions[FeatureFlag.coder_inherits_planner_chat]
    refresh = definitions[FeatureFlag.completion_refresh_on_update]
    scoped = definitions[FeatureFlag.plugin_catalog_scoped_latest]
    prettier = definitions[FeatureFlag.prettier_enabled]

    assert coder.kind == "beta"
    assert coder.default is False
    assert coder.bead == "sase-qe"

    assert refresh.kind == "beta"
    assert refresh.default is False
    assert refresh.bead == "sase-qg"

    assert scoped.kind == "beta"
    assert scoped.default is False
    assert scoped.bead == "sase-qq"

    assert prettier.kind == "sunset"
    assert prettier.default is True
    assert prettier.bead == "sase-qf"


def test_consumer_flags_resolve_from_every_layer() -> None:
    definitions = feature_flag_definitions()

    default = resolve_feature_flags(definitions=definitions, layers=[])
    assert default.enabled(FeatureFlag.coder_inherits_planner_chat) is False
    assert default.enabled(FeatureFlag.prettier_enabled) is True

    user = resolve_feature_flags(
        definitions=definitions,
        layers=[
            layer(
                "user",
                {
                    "coder_inherits_planner_chat": True,
                    "prettier_enabled": False,
                },
                detail="user.yml",
            )
        ],
    )
    assert user.enabled(FeatureFlag.coder_inherits_planner_chat) is True
    assert user.enabled(FeatureFlag.prettier_enabled) is False
    assert user.decision(FeatureFlag.coder_inherits_planner_chat).source == "user"

    env = resolve_feature_flags(
        definitions=definitions,
        layers=[],
        env_value='{"coder_inherits_planner_chat":true,"prettier_enabled":false}',
    )
    assert env.enabled(FeatureFlag.coder_inherits_planner_chat) is True
    assert env.enabled(FeatureFlag.prettier_enabled) is False
    assert env.decision(FeatureFlag.prettier_enabled).source == "env"


def test_consumer_flags_both_states_via_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_DISABLE_PRETTIER", raising=False)
    monkeypatch.delenv("SASE_FEATURE_FLAGS", raising=False)
    with override_flags(
        coder_inherits_planner_chat=True,
        prettier_enabled=False,
    ) as snapshot:
        assert snapshot.enabled(FeatureFlag.coder_inherits_planner_chat) is True
        assert snapshot.enabled(FeatureFlag.prettier_enabled) is False
        assert current_flags().enabled(FeatureFlag.prettier_enabled) is False

    restored = current_flags()
    assert restored.enabled(FeatureFlag.coder_inherits_planner_chat) is False
    assert restored.enabled(FeatureFlag.prettier_enabled) is True


def test_prettier_flag_both_states_reach_the_call_site() -> None:
    with (
        override_flags(prettier_enabled=True),
        patch("sase.file_references.shutil.which", return_value="/usr/bin/prettier"),
        patch("sase.file_references.subprocess.run") as run,
    ):
        run.return_value.stdout = "formatted\n"
        run.return_value.returncode = 0
        assert format_with_prettier("text") == "formatted\n"
        run.assert_called_once()

    with (
        override_flags(prettier_enabled=False),
        patch("sase.file_references.shutil.which", return_value="/usr/bin/prettier"),
        patch("sase.file_references.subprocess.run") as run,
    ):
        assert format_with_prettier("text") == "text"
        run.assert_not_called()
