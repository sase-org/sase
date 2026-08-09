"""Tests for the Python config inventory adapter + Rust-merge parity.

The merge golden mirrors the Rust ``config_parity.rs`` golden: both sides fold
the same fixture layer stack and assert the identical merged result, so a drift
between the Python ``_deep_merge`` and the Rust merge fails on one side or the
other. The remaining tests cover layer serialization, the flattened field
model, and the inventory provenance/source rail through the real binding.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from sase.config.core import ConfigLayer, _deep_merge
from sase.config.inventory import (
    build_config_inventory,
    config_field_model,
    discover_layer_inputs,
    load_config_schema,
)


# The merged config produced by folding the fixture layer stack through the
# Python ``_deep_merge`` — kept identical to ``PYTHON_MERGE_GOLDEN`` in
# ``sase-core``'s ``config_parity.rs`` so the two implementations are pinned to
# the same vectors.
PYTHON_MERGE_GOLDEN: dict[str, Any] = {
    "axe": {
        "chop_script_dirs": ["a", "b", "c"],
        "max_hook_runners": 5,
    },
    "linked_repos": [
        {"name": "user"},
        {"name": "overlay"},
        {"name": "local"},
    ],
    "sibling_repos": [{"name": "dep"}],
    "timezone": "US/Pacific",
    "use_chezmoi": True,
}


def _fixture_layers() -> list[ConfigLayer]:
    """The fixture layer stack mirrored from the Rust parity test."""
    return [
        ConfigLayer(
            name="default",
            path=None,
            exists=True,
            list_strategy="concatenate",
            data={
                "timezone": "America/New_York",
                "use_chezmoi": False,
                "axe": {"max_hook_runners": 3, "chop_script_dirs": ["a"]},
                "linked_repos": [{"name": "core"}],
            },
        ),
        ConfigLayer(
            name="plugin:demo",
            path=None,
            exists=True,
            list_strategy="concatenate",
            data={
                "axe": {"chop_script_dirs": ["b"]},
                "linked_repos": [{"name": "plugin"}],
            },
        ),
        ConfigLayer(
            name="user",
            path="/home/u/.config/sase/sase.yml",
            exists=True,
            list_strategy="replace",
            data={
                "timezone": "US/Pacific",
                "axe": {"max_hook_runners": 5},
                "linked_repos": [{"name": "user"}],
                "sibling_repos": [{"name": "dep"}],
            },
        ),
        ConfigLayer(
            name="overlay:sase_extra.yml",
            path="/home/u/.config/sase/sase_extra.yml",
            exists=True,
            list_strategy="concatenate",
            data={
                "axe": {"chop_script_dirs": ["c"]},
                "linked_repos": [{"name": "overlay"}],
            },
        ),
        ConfigLayer(
            name="local",
            path="/repo/sase.yml",
            exists=True,
            list_strategy="concatenate",
            data={
                "use_chezmoi": True,
                "linked_repos": [{"name": "local"}],
            },
        ),
        ConfigLayer(
            name="overlay:missing.yml",
            path="/home/u/.config/sase/missing.yml",
            exists=False,
            list_strategy="concatenate",
            data={},
        ),
    ]


def _inventory_schema() -> dict[str, Any]:
    """The schema mirrored from the Rust parity test's ``inventory_schema``."""
    return {
        "type": "object",
        "additionalProperties": False,
        "definitions": {
            "repo": {
                "type": "object",
                "required": ["name"],
                "additionalProperties": False,
                "properties": {"name": {"type": "string"}},
            }
        },
        "properties": {
            "timezone": {"type": "string", "default": "America/New_York"},
            "use_chezmoi": {"type": "boolean", "default": False},
            "axe": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "max_hook_runners": {"type": "integer", "default": 3},
                    "chop_script_dirs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": [],
                    },
                },
            },
            "linked_repos": {
                "type": "array",
                "items": {"$ref": "#/definitions/repo"},
                "default": [],
            },
            "sibling_repos": {
                "type": "array",
                "items": {"$ref": "#/definitions/repo"},
            },
        },
    }


def _build_fixture_inventory() -> Any:
    with patch(
        "sase.config.inventory.load_config_layers",
        return_value=_fixture_layers(),
    ):
        return build_config_inventory(schema=_inventory_schema())


# --- Rust/Python merge parity ---------------------------------------------


def test_deep_merge_fold_matches_rust_golden() -> None:
    """Folding the fixture stack through Python ``_deep_merge`` hits the golden.

    This is the Python half of the cross-language parity vector asserted in
    ``sase-core``'s ``merge_layers_matches_python_deep_merge_golden``.
    """
    result: dict[str, Any] = {}
    for layer in _fixture_layers():
        if not layer.data:
            continue
        result = _deep_merge(
            result,
            layer.data,
            list_strategy="replace"
            if layer.list_strategy == "replace"
            else "concatenate",
        )
    assert result == PYTHON_MERGE_GOLDEN


def test_inventory_effective_values_match_merge_golden() -> None:
    """Per-field effective values from the Rust inventory match the golden."""
    inventory = _build_fixture_inventory()
    assert inventory.field("timezone").effective_value == "US/Pacific"
    assert inventory.field("use_chezmoi").effective_value is True
    assert inventory.field("axe.max_hook_runners").effective_value == 5
    assert inventory.field("axe.chop_script_dirs").effective_value == [
        "a",
        "b",
        "c",
    ]
    assert inventory.field("linked_repos").effective_value == [
        {"name": "user"},
        {"name": "overlay"},
        {"name": "local"},
    ]


# --- Provenance & source rail ---------------------------------------------


def test_inventory_reports_scalar_provenance() -> None:
    """A scalar lists each contributor with the highest-priority one winning."""
    inventory = _build_fixture_inventory()
    timezone = inventory.field("timezone")
    layers = [c.layer for c in timezone.contributions]
    assert layers == ["default", "user"]
    assert timezone.contributions[0].winning is False
    assert timezone.contributions[-1].winning is True
    assert timezone.has_default is True
    assert timezone.default == "America/New_York"


def test_inventory_reports_list_provenance_stack() -> None:
    """A concatenated list lists every contributor in priority order."""
    inventory = _build_fixture_inventory()
    linked = inventory.field("linked_repos")
    layers = [c.layer for c in linked.contributions]
    assert layers == [
        "default",
        "plugin:demo",
        "user",
        "overlay:sase_extra.yml",
        "local",
    ]
    assert linked.contributions[-1].winning is True


def test_inventory_attaches_deprecation_replacement() -> None:
    """The deprecation policy attaches a replacement to the deprecated field."""
    inventory = _build_fixture_inventory()
    sibling = inventory.field("sibling_repos")
    assert sibling.deprecated_replacement == "repos.linked"
    assert inventory.field("linked_repos").deprecated_replacement == "repos.linked"


def test_inventory_write_capabilities_are_writable_layers() -> None:
    """Write capabilities list exactly the writable (file-backed) layers."""
    inventory = _build_fixture_inventory()
    assert inventory.field("timezone").write_capabilities == (
        "user",
        "overlay:sase_extra.yml",
        "local",
        "overlay:missing.yml",
    )


def test_inventory_source_rail_flags_and_existence() -> None:
    """Sources flag the deprecated key, writability, and missing files."""
    inventory = _build_fixture_inventory()
    user = inventory.source("user")
    assert user is not None
    assert user.deprecated_keys == ("linked_repos", "sibling_repos")
    assert user.writable is True
    assert user.kind == "user"

    default = inventory.source("default")
    assert default is not None
    assert default.writable is False  # package-backed layer, no path

    missing = inventory.source("overlay:missing.yml")
    assert missing is not None
    assert missing.exists is False
    assert missing.key_count == 0


def test_inventory_emits_deprecated_key_diagnostic() -> None:
    """A deprecated-key diagnostic is emitted for the offending layer."""
    inventory = _build_fixture_inventory()
    assert any(
        d.code == "deprecated_key" and d.layer == "user" and d.path == "sibling_repos"
        for d in inventory.diagnostics
    )


# --- Layer serialization --------------------------------------------------


def test_discover_layer_inputs_serializes_writability_and_kind() -> None:
    """Serialized inputs derive kind from the name and writability from path."""
    with patch(
        "sase.config.inventory.load_config_layers",
        return_value=_fixture_layers(),
    ):
        inputs = discover_layer_inputs()
    by_name = {layer["name"]: layer for layer in inputs}
    assert by_name["default"]["kind"] == "builtin"
    assert by_name["default"]["writable"] is False
    assert by_name["plugin:demo"]["kind"] == "plugin"
    assert by_name["user"]["kind"] == "user"
    assert by_name["user"]["writable"] is True
    assert by_name["overlay:sase_extra.yml"]["kind"] == "overlay"
    assert by_name["local"]["kind"] == "local"


def test_discover_layer_inputs_replaces_local_with_explicit_path(
    tmp_path: Any,
) -> None:
    """Explicit local paths replace the auto-discovered local layer."""
    local_file = tmp_path / "sase.yml"
    local_file.write_text("timezone: US/Eastern\n", encoding="utf-8")
    layers = _fixture_layers()
    # Swap the missing overlay for an auto local layer to prove it is dropped.
    layers[-1] = ConfigLayer(
        name="local",
        path="/auto/sase.yml",
        exists=False,
        list_strategy="concatenate",
        data={},
    )
    with patch("sase.config.inventory.load_config_layers", return_value=layers):
        inputs = discover_layer_inputs(local_paths=(local_file,))
    locals_ = [layer for layer in inputs if layer["kind"] == "local"]
    assert len(locals_) == 1
    assert locals_[0]["path"] == str(local_file)
    assert locals_[0]["value"] == {"timezone": "US/Eastern"}
    assert locals_[0]["exists"] is True


# --- Field model ----------------------------------------------------------


def test_config_field_model_flattens_real_schema() -> None:
    """The real schema flattens into dotted-path fields with classifications."""
    model = config_field_model()
    by_path = {f.path: f for f in model.fields}
    # The canonical nested fields and deprecated aliases are all visible.
    assert "repos.linked" in by_path
    assert "repos.sidecar" in by_path
    assert "id.username" in by_path
    assert "id.machine_name" in by_path
    assert "machine_name" in by_path
    assert by_path["machine_name"].deprecated is True
    assert "linked_repos" in by_path
    assert by_path["linked_repos"].kind == "array"


def test_load_config_schema_returns_object_schema() -> None:
    """The bundled schema loads as a draft-07 object schema and is cached."""
    schema = load_config_schema()
    assert schema["type"] == "object"
    # Cached: a second call returns the same object.
    assert load_config_schema() is schema


def test_inventory_diagnoses_glossary_outside_project_local_config(
    tmp_path,
) -> None:
    local_file = tmp_path / "sase.yml"
    local_file.write_text(
        "glossary:\n  Workspace:\n    definition: A numbered checkout.\n",
        encoding="utf-8",
    )
    layers = [
        ConfigLayer(
            name="default",
            path=None,
            exists=True,
            list_strategy="concatenate",
            data={},
        ),
        ConfigLayer(
            name="user",
            path="/home/u/.config/sase/sase.yml",
            exists=True,
            list_strategy="concatenate",
            data={"glossary": {"Agent Clan": {"definition": "A named container."}}},
        ),
    ]

    with patch("sase.config.inventory.load_config_layers", return_value=layers):
        inventory = build_config_inventory(local_paths=(local_file,))

    assert any(
        diagnostic.code == "glossary_scope"
        and diagnostic.layer == "user"
        and diagnostic.path == "glossary"
        for diagnostic in inventory.diagnostics
    )
    assert not any(
        diagnostic.code == "glossary_scope" and diagnostic.layer == "local"
        for diagnostic in inventory.diagnostics
    )


def test_inventory_diagnoses_nested_glossary_outside_project_local_config(
    tmp_path,
) -> None:
    local_file = tmp_path / "sase.yml"
    local_file.write_text(
        "memory:\n  glossary:\n    Workspace:\n      definition: A numbered checkout.\n",
        encoding="utf-8",
    )
    layers = [
        ConfigLayer(
            name="default",
            path=None,
            exists=True,
            list_strategy="concatenate",
            data={},
        ),
        ConfigLayer(
            name="user",
            path="/home/u/.config/sase/sase.yml",
            exists=True,
            list_strategy="concatenate",
            data={
                "memory": {
                    "glossary": {"Agent Clan": {"definition": "A named container."}}
                }
            },
        ),
    ]

    with patch("sase.config.inventory.load_config_layers", return_value=layers):
        inventory = build_config_inventory(local_paths=(local_file,))

    assert any(
        diagnostic.code == "glossary_scope"
        and diagnostic.layer == "user"
        and diagnostic.path == "memory.glossary"
        for diagnostic in inventory.diagnostics
    )
    assert not any(
        diagnostic.code == "glossary_scope" and diagnostic.layer == "local"
        for diagnostic in inventory.diagnostics
    )
