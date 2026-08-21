"""Tests for the shared ``<plugin>@<id>`` ``use:`` value parser."""

from __future__ import annotations

import pytest

from sase.plugins.qualified_id import (
    PluginQualifiedIdError,
    canonical_plugin_qualified_id,
    parse_plugin_qualified_id,
    plugin_qualified_id_matches,
)


@pytest.mark.parametrize(
    ("value", "plugin", "id_"),
    [
        ("builtin@plan", "builtin", "plan"),
        ("sase-research-artifacts@research", "sase-research-artifacts", "research"),
        (
            "sase_research_artifacts@research-highlights",
            "sase_research_artifacts",
            "research-highlights",
        ),
    ],
)
def test_parse_plugin_qualified_id_accepts_valid_values(
    value: str, plugin: str, id_: str
) -> None:
    assert parse_plugin_qualified_id(value) == (plugin, id_)


@pytest.mark.parametrize(
    "value",
    [
        "plan",
        "research",
        "@plan",
        "builtin@",
        "builtin@Plan",
        "builtin@-plan",
        "builtin@plan@extra",
        "",
    ],
)
def test_parse_plugin_qualified_id_rejects_bad_values(value: str) -> None:
    with pytest.raises(PluginQualifiedIdError):
        parse_plugin_qualified_id(value)


def test_plugin_qualified_id_matches_builtin() -> None:
    assert plugin_qualified_id_matches("builtin", builtin=True, package="sase")
    assert not plugin_qualified_id_matches("builtin", builtin=False, package="sase")


def test_plugin_qualified_id_matches_installed_package() -> None:
    assert plugin_qualified_id_matches(
        "sase-research-artifacts", builtin=False, package="sase-research-artifacts"
    )
    assert not plugin_qualified_id_matches(
        "sase-research-artifacts", builtin=False, package="sase-other-plugin"
    )
    assert not plugin_qualified_id_matches(
        "sase-research-artifacts", builtin=True, package="sase"
    )


def test_plugin_qualified_id_matches_packaging_equivalent_names() -> None:
    assert plugin_qualified_id_matches(
        "Example_Finalizers", builtin=False, package="Example.Finalizers"
    )
    assert plugin_qualified_id_matches(
        "example-finalizers", builtin=False, package="Example_Finalizers"
    )


def test_canonical_plugin_qualified_id_normalizes_distribution_segment() -> None:
    assert (
        canonical_plugin_qualified_id("Example_Finalizers@audit")
        == "example-finalizers@audit"
    )
    assert canonical_plugin_qualified_id("Builtin@commit") == "builtin@commit"
