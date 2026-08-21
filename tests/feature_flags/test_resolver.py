"""Feature-flag resolver tests."""

from __future__ import annotations

import pytest

from sase.feature_flags import FeatureFlagEnvError
from sase.feature_flags.env import SASE_FEATURE_FLAGS_ENV
from sase.feature_flags.resolver import resolve_feature_flags

from ._helpers import definitions, demo_flag, layer


@pytest.mark.parametrize(
    ("layer_name", "detail", "source"),
    [
        ("user", "/home/u/.config/sase/sase.yml", "user"),
        ("overlay:extra.yml", "/home/u/.config/sase/extra.yml", "overlay"),
    ],
)
def test_authoritative_layers_resolve_with_provenance(
    layer_name: str,
    detail: str,
    source: str,
) -> None:
    snapshot = resolve_feature_flags(
        definitions=definitions(demo_flag()),
        layers=[layer(layer_name, {"demo_flag": True}, detail=detail)],
    )

    decision = snapshot.decision("demo_flag")
    assert decision.enabled is True
    assert decision.source == source
    assert decision.source_detail == detail
    assert decision.overridden is True


def test_last_writer_wins_across_authoritative_layers() -> None:
    snapshot = resolve_feature_flags(
        definitions=definitions(demo_flag()),
        layers=[
            layer("user", {"demo_flag": True}, detail="user.yml"),
            layer("overlay:a.yml", {"demo_flag": False}, detail="a.yml"),
            layer("overlay:b.yml", {"demo_flag": True}, detail="b.yml"),
        ],
    )

    decision = snapshot.decision("demo_flag")
    assert decision.enabled is True
    assert decision.source == "overlay"
    assert decision.source_detail == "b.yml"
    assert decision.overridden is True


def test_default_layer_warns_and_plugin_layer_is_silent() -> None:
    definitions_by_key = definitions(demo_flag())

    default_snapshot = resolve_feature_flags(
        definitions=definitions_by_key,
        layers=[layer("default", {"demo_flag": True})],
    )
    assert default_snapshot.enabled("demo_flag") is False
    assert [diagnostic.code for diagnostic in default_snapshot.diagnostics] == [
        "default_layer_ignored"
    ]

    plugin_snapshot = resolve_feature_flags(
        definitions=definitions_by_key,
        layers=[layer("plugin:demo", {"demo_flag": True})],
    )
    assert plugin_snapshot.enabled("demo_flag") is False
    assert plugin_snapshot.diagnostics == ()


def test_local_layer_always_violates_scope() -> None:
    snapshot = resolve_feature_flags(
        definitions=definitions(
            demo_flag("alpha_flag"),
            demo_flag("beta_flag"),
        ),
        layers=[
            layer(
                "local",
                {
                    "alpha_flag": True,
                    "beta_flag": True,
                },
            )
        ],
    )

    assert snapshot.enabled("alpha_flag") is False
    assert snapshot.enabled("beta_flag") is False
    assert snapshot.decision("alpha_flag").source == "default"
    assert snapshot.decision("beta_flag").source == "default"
    assert [diagnostic.code for diagnostic in snapshot.diagnostics] == [
        "scope_violation",
        "scope_violation",
    ]


def test_project_scope_cannot_be_registered_or_locally_resolved() -> None:
    """sase-o2's project-scope premise is inapplicable: flags are global-only.

    Definitions have no scope field, local config is always a scope violation,
    and the inherited SASE_FEATURE_FLAGS snapshot still pins child processes.
    """
    from dataclasses import fields

    from sase.feature_flags.models import FeatureFlagDefinition

    assert "scope" not in {item.name for item in fields(FeatureFlagDefinition)}
    with pytest.raises(TypeError, match="scope"):
        FeatureFlagDefinition(
            key=demo_flag().key,
            kind="beta",
            description="x",
            bead="sase-x",
            scope="project",  # type: ignore[call-arg]
        )

    snapshot = resolve_feature_flags(
        definitions=definitions(demo_flag()),
        layers=[layer("local", {"demo_flag": True}, detail="project.yml")],
    )
    assert snapshot.enabled("demo_flag") is False
    assert snapshot.decision("demo_flag").source == "default"
    assert [diagnostic.code for diagnostic in snapshot.diagnostics] == [
        "scope_violation"
    ]


def test_unknown_and_non_boolean_file_values_warn_and_leave_prior_decision() -> None:
    snapshot = resolve_feature_flags(
        definitions=definitions(demo_flag()),
        layers=[
            layer("user", {"demo_flag": True}),
            layer("overlay:bad.yml", {"demo_flag": 1, "missing_flag": True}),
        ],
    )

    assert snapshot.enabled("demo_flag") is True
    assert snapshot.decision("demo_flag").source == "user"
    assert [diagnostic.code for diagnostic in snapshot.diagnostics] == [
        "not_boolean",
        "unknown_key",
    ]


def test_legacy_disable_env_maps_to_flag_and_warns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.feature_flags import env as env_mod
    from sase.feature_flags.env import _LegacyEnvMapping

    monkeypatch.setattr(
        env_mod,
        "_LEGACY_ENV_MAPPINGS",
        (_LegacyEnvMapping(name="SASE_DISABLE_DEMO", key="demo_flag", invert=True),),
    )
    snapshot = resolve_feature_flags(
        definitions=definitions(demo_flag(kind="sunset")),
        layers=[layer("user", {"demo_flag": True})],
        legacy_env={"SASE_DISABLE_DEMO": "1"},
    )

    decision = snapshot.decision("demo_flag")
    assert decision.enabled is False
    assert decision.source == "env"
    assert decision.source_detail == "SASE_DISABLE_DEMO"
    assert [diagnostic.code for diagnostic in snapshot.diagnostics] == [
        "deprecated_env"
    ]
    assert "SASE_DISABLE_DEMO" in snapshot.diagnostics[0].message


def test_override_and_feature_flags_env_beat_legacy_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.feature_flags import env as env_mod
    from sase.feature_flags.env import _LegacyEnvMapping

    monkeypatch.setattr(
        env_mod,
        "_LEGACY_ENV_MAPPINGS",
        (_LegacyEnvMapping(name="SASE_DISABLE_DEMO", key="demo_flag", invert=True),),
    )
    overridden = resolve_feature_flags(
        definitions=definitions(demo_flag(kind="sunset")),
        layers=[],
        overrides={"demo_flag": True},
        legacy_env={"SASE_DISABLE_DEMO": "1"},
    )
    assert overridden.enabled("demo_flag") is True
    assert overridden.decision("demo_flag").source == "override"
    assert [diagnostic.code for diagnostic in overridden.diagnostics] == [
        "deprecated_env"
    ]

    env_wins = resolve_feature_flags(
        definitions=definitions(demo_flag(kind="sunset")),
        layers=[],
        legacy_env={"SASE_DISABLE_DEMO": "1"},
        env_value='{"demo_flag":true}',
    )
    assert env_wins.enabled("demo_flag") is True
    assert env_wins.decision("demo_flag").source == "env"
    assert env_wins.decision("demo_flag").source_detail == SASE_FEATURE_FLAGS_ENV
    assert [diagnostic.code for diagnostic in env_wins.diagnostics] == [
        "deprecated_env"
    ]


def test_legacy_env_is_ignored_for_unregistered_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.feature_flags import env as env_mod
    from sase.feature_flags.env import _LegacyEnvMapping

    monkeypatch.setattr(
        env_mod,
        "_LEGACY_ENV_MAPPINGS",
        (
            _LegacyEnvMapping(
                name="SASE_DISABLE_DEMO",
                key="missing_flag",
                invert=True,
            ),
        ),
    )
    snapshot = resolve_feature_flags(
        definitions=definitions(demo_flag()),
        layers=[],
        legacy_env={"SASE_DISABLE_DEMO": "1"},
    )

    assert snapshot.enabled("demo_flag") is False
    assert snapshot.diagnostics == ()


def test_empty_legacy_env_does_not_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.feature_flags import env as env_mod
    from sase.feature_flags.env import _LegacyEnvMapping

    monkeypatch.setattr(
        env_mod,
        "_LEGACY_ENV_MAPPINGS",
        (_LegacyEnvMapping(name="SASE_DISABLE_DEMO", key="demo_flag", invert=True),),
    )
    snapshot = resolve_feature_flags(
        definitions=definitions(demo_flag(kind="sunset")),
        layers=[],
        legacy_env={"SASE_DISABLE_DEMO": ""},
    )

    assert snapshot.enabled("demo_flag") is True
    assert snapshot.decision("demo_flag").source == "default"
    assert snapshot.diagnostics == ()


def test_cli_beats_env_override_and_config_layers() -> None:
    snapshot = resolve_feature_flags(
        definitions=definitions(demo_flag()),
        layers=[
            layer("user", {"demo_flag": False}, detail="user.yml"),
            layer("overlay:extra.yml", {"demo_flag": False}, detail="extra.yml"),
            layer("local", {"demo_flag": False}, detail="local.yml"),
        ],
        overrides={"demo_flag": False},
        env_value='{"demo_flag":false}',
        cli={"demo_flag": True},
    )

    decision = snapshot.decision("demo_flag")
    assert decision.enabled is True
    assert decision.source == "cli"
    assert decision.source_detail == "--enable-feature"
    assert decision.overridden is True


def test_cli_disable_beats_env_and_records_disable_option() -> None:
    snapshot = resolve_feature_flags(
        definitions=definitions(demo_flag(kind="sunset")),
        layers=[],
        overrides={"demo_flag": True},
        env_value='{"demo_flag":true}',
        cli={"demo_flag": False},
    )

    decision = snapshot.decision("demo_flag")
    assert decision.enabled is False
    assert decision.source == "cli"
    assert decision.source_detail == "--disable-feature"


def test_cli_can_set_a_flag() -> None:
    snapshot = resolve_feature_flags(
        definitions=definitions(demo_flag("demo_flag")),
        layers=[],
        cli={"demo_flag": True},
    )

    decision = snapshot.decision("demo_flag")
    assert decision.enabled is True
    assert decision.source == "cli"
    assert decision.source_detail == "--enable-feature"


def test_env_beats_overrides_and_unknown_env_key_warns_only() -> None:
    snapshot = resolve_feature_flags(
        definitions=definitions(demo_flag()),
        layers=[],
        overrides={"demo_flag": True},
        env_value='{"demo_flag":false,"future_flag":true}',
    )

    decision = snapshot.decision("demo_flag")
    assert decision.enabled is False
    assert decision.source == "env"
    assert decision.source_detail == SASE_FEATURE_FLAGS_ENV
    assert [diagnostic.code for diagnostic in snapshot.diagnostics] == ["unknown_key"]
    assert snapshot.diagnostics[0].source == "env"


@pytest.mark.parametrize("raw", ["not json", "[]", '{"demo_flag": 1}'])
def test_malformed_env_is_fatal(raw: str) -> None:
    with pytest.raises(FeatureFlagEnvError):
        resolve_feature_flags(
            definitions=definitions(demo_flag()),
            layers=[],
            env_value=raw,
        )
