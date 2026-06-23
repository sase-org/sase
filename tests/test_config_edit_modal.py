"""Pure-logic tests for the Config Center edit flow (Phase 5).

These exercise the schema/value helpers and scope policy that drive the typed
editors without standing up a Textual app: editor-kind selection from the
schema, schema-path walking (incl. ``$ref``), value formatting/parsing with
constraint enforcement, the YAML escape hatch round-trip, the list-strategy
banner, and the default-target rules. The modal widget wiring (worker plan +
preview + write) is covered by ``tests/ace/tui/test_config_edit_modal_widget.py``
and the backend itself by ``tests/test_config_edit.py``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.modals import config_edit_modal as cem
from sase.ace.tui.modals import config_pane as cp
from sase.config import ConfigConstraints, ConfigField
from sase.config.inventory import build_config_inventory, config_field_model
from tests.test_config_pane import _fixture_layers, _fixture_schema


@pytest.fixture
def view() -> cp.ConfigPaneView:
    schema = _fixture_schema()
    with patch(
        "sase.config.inventory.load_config_layers",
        return_value=_fixture_layers(),
    ):
        inventory = build_config_inventory(schema=schema)
    field_model = config_field_model(schema=schema)
    return cp.ConfigPaneView.build(field_model, inventory)


def _field(
    path: str,
    kind: str,
    types: tuple[str, ...],
    *,
    enum: tuple[Any, ...] = (),
    **constraints: Any,
) -> ConfigField:
    return ConfigField(
        path=path,
        name=path.split(".")[-1],
        depth=0,
        parent=None,
        kind=kind,
        leaf=True,
        types=types,
        description="",
        has_default=False,
        default=None,
        enum_values=enum,
        deprecated=False,
        deprecated_replacement=None,
        constraints=ConfigConstraints(
            minimum=constraints.get("minimum"),
            maximum=constraints.get("maximum"),
            exclusive_minimum=constraints.get("exclusive_minimum"),
            exclusive_maximum=constraints.get("exclusive_maximum"),
            min_length=constraints.get("min_length"),
            max_length=constraints.get("max_length"),
            pattern=None,
        ),
        additional_properties_allowed=False,
    )


# --- editor kind selection -------------------------------------------------


def test_editor_kind_for_scalars(view: cp.ConfigPaneView) -> None:
    schema = view.inventory.schema
    assert (
        cem._editor_kind_for(view.fields_by_path["timezone"], schema, "x") == "string"
    )
    assert (
        cem._editor_kind_for(view.fields_by_path["use_chezmoi"], schema, True) == "bool"
    )
    assert (
        cem._editor_kind_for(view.fields_by_path["axe.max_hook_runners"], schema, 3)
        == "int"
    )


def test_editor_kind_for_arrays(view: cp.ConfigPaneView) -> None:
    schema = view.inventory.schema
    # array<string> -> line editor.
    assert (
        cem._editor_kind_for(view.fields_by_path["axe.chop_script_dirs"], schema, [])
        == "string_list"
    )
    # array<object> -> raw YAML escape hatch.
    assert (
        cem._editor_kind_for(view.fields_by_path["linked_repos"], schema, []) == "yaml"
    )


def test_editor_kind_enum_wins() -> None:
    field = _field("mode", "scalar", ("string",), enum=("a", "b"))
    assert cem._editor_kind_for(field, {}, "a") == "enum"


def test_editor_kind_number_vs_int() -> None:
    assert cem._editor_kind_for(_field("a", "scalar", ("number",)), {}, 1.0) == "number"
    assert cem._editor_kind_for(_field("a", "scalar", ("integer",)), {}, 1) == "int"
    # A numeric/string union is treated as a free-text string field.
    assert (
        cem._editor_kind_for(_field("a", "scalar", ("integer", "string")), {}, 1)
        == "string"
    )


def test_editor_kind_string_list_falls_back_to_value_when_items_unknown() -> None:
    # No schema item type, but the current value is a list of strings.
    field = _field("dirs", "array", ("array",))
    assert cem._editor_kind_for(field, {}, ["a", "b"]) == "string_list"
    assert cem._editor_kind_for(field, {}, [{"k": 1}]) == "yaml"


# --- schema walking --------------------------------------------------------


def test_array_item_type_resolves_ref() -> None:
    schema = {
        "type": "object",
        "properties": {"repos": {"type": "array", "items": {"$ref": "#/$defs/Repo"}}},
        "$defs": {
            "Repo": {"type": "object", "properties": {"name": {"type": "string"}}}
        },
    }
    assert cem._array_item_type(schema, "repos") == "object"


def test_schema_node_for_path_nested() -> None:
    schema = {
        "type": "object",
        "properties": {
            "axe": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
            }
        },
    }
    node = cem._schema_node_for_path(schema, "axe.query")
    assert node == {"type": "string"}
    assert cem._schema_node_for_path(schema, "axe.missing") is None


# --- value formatting / parsing -------------------------------------------


def test_format_value_for_editor() -> None:
    assert cem._format_value_for_editor("string", "hi") == "hi"
    assert cem._format_value_for_editor("int", 5) == "5"
    assert cem._format_value_for_editor("string", None) == ""
    assert cem._format_value_for_editor("string_list", ["a", "b"]) == "a\nb"
    assert cem._format_value_for_editor("yaml", [{"name": "x"}]).strip() == "- name: x"


def test_parse_editor_value_int_and_number() -> None:
    field = _field("n", "scalar", ("integer",))
    assert cem._parse_editor_value("int", " 7 ", field) == (7, None)
    value, error = cem._parse_editor_value("int", "nope", field)
    assert value is None and error is not None
    assert cem._parse_editor_value("number", "1.5", field)[0] == 1.5


def test_parse_editor_value_enforces_constraints() -> None:
    field = _field("n", "scalar", ("integer",), minimum=1, maximum=10)
    assert cem._parse_editor_value("int", "0", field)[1] is not None  # < min
    assert cem._parse_editor_value("int", "11", field)[1] is not None  # > max
    assert cem._parse_editor_value("int", "5", field) == (5, None)


def test_parse_editor_value_string_list_drops_blank_lines() -> None:
    field = _field("dirs", "array", ("array",))
    value, error = cem._parse_editor_value("string_list", "a\n  b  \n\n c\n", field)
    assert error is None
    assert value == ["a", "b", "c"]


def test_parse_editor_value_yaml_roundtrip_and_error() -> None:
    field = _field("repos", "array", ("array",))
    value, error = cem._parse_editor_value("yaml", "- name: x\n- name: y", field)
    assert error is None
    assert value == [{"name": "x"}, {"name": "y"}]
    # Plain JSON-able types (not ruamel Commented* containers).
    assert type(value) is list and type(value[0]) is dict
    bad_value, bad_error = cem._parse_editor_value("yaml", "key: [unterminated", field)
    assert bad_value is None and bad_error is not None


# --- banners / scope policy ------------------------------------------------


def test_list_strategy_banner_replace_vs_append(view: cp.ConfigPaneView) -> None:
    user = view.inventory.source("user")
    overlay = view.inventory.source("overlay:sase_extra.yml")
    assert user is not None and overlay is not None
    assert "replace" in cem._list_strategy_banner(user).plain
    assert "append" in cem._list_strategy_banner(overlay).plain


def test_initial_target_prefers_writable_winning_layer(
    view: cp.ConfigPaneView,
) -> None:
    # timezone is set by the user layer -> default to user.
    field = view.fields_by_path["timezone"]
    assert cem._initial_target(view.inventory, field, view) == "user"
    # chop_script_dirs is set only by the overlay -> default to the overlay.
    arr = view.fields_by_path["axe.chop_script_dirs"]
    assert cem._initial_target(view.inventory, arr, view) == "overlay:sase_extra.yml"


def test_initial_target_falls_back_for_unset_field(view: cp.ConfigPaneView) -> None:
    # use_chezmoi is only the built-in default -> falls back to the user base.
    field = view.fields_by_path["use_chezmoi"]
    assert cem._initial_target(view.inventory, field, view) == "user"
