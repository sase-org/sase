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
        ("local", "/repo/sase/sase.yml", "local"),
    ],
)
def test_authoritative_layers_resolve_with_provenance(
    layer_name: str,
    detail: str,
    source: str,
) -> None:
    snapshot = resolve_feature_flags(
        definitions=definitions(demo_flag(default=False)),
        layers=[layer(layer_name, {"demo_flag": True}, detail=detail)],
    )

    decision = snapshot.decision("demo_flag")
    assert decision.enabled is True
    assert decision.source == source
    assert decision.source_detail == detail
    assert decision.overridden is True


def test_last_writer_wins_across_authoritative_layers() -> None:
    snapshot = resolve_feature_flags(
        definitions=definitions(demo_flag(default=False)),
        layers=[
            layer("user", {"demo_flag": True}, detail="user.yml"),
            layer("overlay:a.yml", {"demo_flag": False}, detail="a.yml"),
            layer("overlay:b.yml", {"demo_flag": True}, detail="b.yml"),
            layer("local", {"demo_flag": False}, detail="local.yml"),
        ],
    )

    decision = snapshot.decision("demo_flag")
    assert decision.enabled is False
    assert decision.source == "local"
    assert decision.source_detail == "local.yml"
    assert decision.overridden is True


def test_default_layer_warns_and_plugin_layer_is_silent() -> None:
    definitions_by_key = definitions(demo_flag(default=False))

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


def test_local_scope_violation_ignores_global_flag_but_project_flag_wins() -> None:
    snapshot = resolve_feature_flags(
        definitions=definitions(
            demo_flag("global_flag", scope="global"),
            demo_flag("project_flag", scope="project"),
        ),
        layers=[
            layer(
                "local",
                {
                    "global_flag": True,
                    "project_flag": True,
                },
            )
        ],
    )

    assert snapshot.enabled("global_flag") is False
    assert snapshot.enabled("project_flag") is True
    assert snapshot.decision("project_flag").source == "local"
    assert [diagnostic.code for diagnostic in snapshot.diagnostics] == [
        "scope_violation"
    ]


def test_unknown_and_non_boolean_file_values_warn_and_leave_prior_decision() -> None:
    snapshot = resolve_feature_flags(
        definitions=definitions(demo_flag(default=False)),
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


def test_env_beats_overrides_and_unknown_env_key_warns_only() -> None:
    snapshot = resolve_feature_flags(
        definitions=definitions(demo_flag(default=False)),
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
