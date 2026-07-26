"""Pure sparse schema-object form coverage."""

from __future__ import annotations

from sase.ace.tui.modals.schema_object_form import SchemaObjectForm


_SCHEMA = {
    "definitions": {
        "duration": {
            "type": "string",
            "minLength": 2,
            "pattern": r"^\d+[smh]$",
        }
    },
    "type": "object",
    "required": ["script"],
    "properties": {
        "description": {"type": "string"},
        "script": {"type": "string", "minLength": 1},
        "run.every": {
            "$ref": "#/definitions/duration",
            "description": "Dotted names remain one path segment.",
        },
        "enabled": {"type": "boolean", "default": True},
        "env": {"type": "object", "additionalProperties": True},
    },
}


def _form() -> SchemaObjectForm:
    return SchemaObjectForm.build(
        schema_root=_SCHEMA,
        object_schema=_SCHEMA,
        effective_values={"script": "daily", "enabled": True, "env": {"A": "1"}},
        target_values={"script": "daily"},
        inherited_values={"enabled": True, "env": {"A": "1"}},
        provenance={"script": "user", "enabled": ("default",)},
        key_prefix=("axe", "lumber.jack", "chops", "daily"),
        basics=("description", "script", "enabled", "run.every"),
        advanced=("env",),
    )


def test_schema_order_is_grouped_required_first_and_refs_are_resolved() -> None:
    form = _form()
    assert [field.name for field in form.fields] == [
        "script",
        "description",
        "enabled",
        "run.every",
        "env",
    ]
    duration = form.field("run.every")
    assert duration.description == "Dotted names remain one path segment."
    assert duration.constraints.min_length == 2
    assert duration.editor_kind == "string"
    assert form.field("env").editor_kind == "yaml"


def test_untouched_effective_values_do_not_leak_into_sparse_patch() -> None:
    form = _form()
    assert form.operations() == ()
    assert form.field("script").has_target
    assert form.field("enabled").effective_value is True
    assert form.field("enabled").source == "default"


def test_set_and_reset_emit_exact_segment_operations() -> None:
    form = _form().set_text("run.every", "15m", live=True).reset_field("script")
    patch = form.patch()
    assert not patch.is_valid
    assert patch.diagnostics[0].code == "required"
    assert [operation.kind for operation in patch.operations] == ["unset", "set"]
    dotted = patch.operations[1]
    assert dotted.key_path == (
        "axe",
        "lumber.jack",
        "chops",
        "daily",
        "run.every",
    )
    assert dotted.value == "15m"


def test_required_and_pattern_diagnostics_are_pure() -> None:
    required_reset = _form().reset_field("script").patch()
    assert not required_reset.is_valid
    assert required_reset.diagnostics[0].code == "required"

    required_blank = _form().set_value("script", "").patch()
    assert not required_blank.is_valid
    assert required_blank.diagnostics[0].message == "required field must have a value"

    invalid = _form().set_text("run.every", "whenever", live=True).patch()
    assert not invalid.is_valid
    assert "pattern" in invalid.diagnostics[0].message


def test_compound_yaml_and_large_live_parse() -> None:
    form = _form().set_text("env", "B: two\n", live=True)
    operation = form.operations()[0]
    assert operation.value == {"B": "two"}

    large_text = "key: " + "x" * 17_000
    deferred = _form().set_text("env", large_text, live=True)
    assert deferred.field("env").parse_deferred
    final_patch = deferred.patch()
    assert final_patch.is_valid
    assert final_patch.operations[0].value == {"key": "x" * 17_000}
