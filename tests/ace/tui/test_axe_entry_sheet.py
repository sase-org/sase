"""Pure AXE single-page property-sheet presentation coverage."""

from __future__ import annotations

from typing import Any

from sase.ace.tui.modals.axe_entry_editor_types import (
    AxeEntryEditorSeed,
    AxeEntryIdentity,
    AxeWritableScope,
    build_axe_entry_form,
)
from sase.ace.tui.modals.axe_entry_sheet import (
    build_sheet_rows,
    detail_dock_lines,
    hint_text,
    sheet_column_widths,
    status_line_text,
)
from sase.ace.tui.modals.schema_object_form import SchemaObjectForm


def test_all_fields_are_grouped_and_unknown_schema_fields_default_advanced() -> None:
    chop_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "script": {"type": "string"},
            "description": {"type": "string"},
            "enabled": {"type": "boolean"},
            "future_policy": {"type": "string"},
            "env": {"type": "object"},
        },
    }
    chop = build_axe_entry_form(
        AxeEntryEditorSeed(
            identity=AxeEntryIdentity("chop", "checks", "lint"),
            schema=chop_schema,
            writable_scopes=(AxeWritableScope("user"),),
        )
    )
    assert [(field.name, field.group) for field in chop.fields] == [
        ("description", "basics"),
        ("script", "basics"),
        ("enabled", "basics"),
        ("env", "advanced"),
        ("future_policy", "advanced"),
    ]

    lumberjack_schema = {
        "type": "object",
        "properties": {
            "description": {"type": "string"},
            "interval": {"type": "integer"},
            "chop_timeout": {"type": "string"},
            "env": {"type": "object"},
            "future_limit": {"type": "integer"},
            "chops": {"type": "object"},
        },
    }
    lumberjack = build_axe_entry_form(
        AxeEntryEditorSeed(
            identity=AxeEntryIdentity("lumberjack", "checks"),
            schema=lumberjack_schema,
            writable_scopes=(AxeWritableScope("user"),),
        )
    )
    assert [(field.name, field.group) for field in lumberjack.fields] == [
        ("description", "basics"),
        ("interval", "basics"),
        ("chop_timeout", "basics"),
        ("env", "advanced"),
        ("future_limit", "advanced"),
    ]


def _state_form() -> SchemaObjectForm:
    schema = {
        "type": "object",
        "properties": {
            "target": {"type": "string"},
            "inherited": {"type": "string"},
            "unset": {"type": "string"},
            "edited": {"type": "string"},
            "inherit": {"type": "string"},
            "invalid": {"type": "integer"},
        },
    }
    form = SchemaObjectForm.build(
        schema_root=schema,
        object_schema=schema,
        effective_values={
            "target": "local",
            "inherited": "parent",
            "inherit": "override",
        },
        target_values={"target": "local", "inherit": "override"},
        inherited_values={"inherited": "parent", "inherit": "parent"},
        provenance={
            "target": "user",
            "inherited": "default",
            "inherit": ("default", "user"),
        },
    )
    form = form.set_value("edited", "draft")
    form = form.reset_field("inherit")
    return form.set_text("invalid", "oops", live=True)


def test_six_row_states_have_stable_values_badges_and_styles() -> None:
    rows = build_sheet_rows(_state_form(), target="user")
    by_name = {row.name: row for row in rows}

    assert (by_name["target"].state, by_name["target"].badge) == (
        "target",
        "·user",
    )
    assert (by_name["inherited"].state, by_name["inherited"].badge) == (
        "inherited",
        "·default",
    )
    assert (by_name["unset"].state, by_name["unset"].value) == ("unset", "—")
    assert (by_name["edited"].state, by_name["edited"].badge) == (
        "edited",
        "edited",
    )
    assert (by_name["inherit"].state, by_name["inherit"].value) == (
        "inherit",
        "parent",
    )
    assert (by_name["invalid"].state, by_name["invalid"].value) == (
        "invalid",
        "oops",
    )
    assert by_name["invalid"].badge_style == "invalid"


def test_value_summaries_cover_scalars_maps_lists_and_multiline_text() -> None:
    schema = {
        "type": "object",
        "properties": {
            "enabled": {"type": "boolean"},
            "env": {"type": "object"},
            "vars": {"type": "object"},
            "for_each": {"type": "array"},
            "description": {"type": "string"},
            "timeout": {"type": "string"},
        },
    }
    values = {
        "enabled": True,
        "env": {"MODE": "strict"},
        "vars": {"a": 1, "b": 2},
        "for_each": [{"a": 1}, {"a": 2}],
        "description": "first\nsecond",
    }
    form = SchemaObjectForm.build(
        schema_root=schema,
        object_schema=schema,
        effective_values=values,
        target_values=values,
    )
    rows = {row.name: row.value for row in build_sheet_rows(form, target="user")}
    assert rows == {
        "enabled": "true",
        "env": "MODE: strict",
        "vars": "2 entries",
        "for_each": "2 targets",
        "description": "first second",
        "timeout": "—",
    }


def test_column_widths_keep_value_space_and_drop_badge_when_narrow() -> None:
    rows = build_sheet_rows(_state_form(), target="overlay:project")
    wide = sheet_column_widths(rows, width=92)
    narrow = sheet_column_widths(rows, width=54, narrow=True)

    assert wide.name >= len("inherited")
    assert wide.value > narrow.value
    assert wide.badge >= len("·overlay:project")
    assert narrow.badge == 0
    assert narrow.value >= 8


def test_detail_dock_handles_description_and_missing_layer_values() -> None:
    schema = {
        "type": "object",
        "required": ["script"],
        "properties": {
            "script": {"type": "string", "description": "Executable to run."},
            "optional": {"type": "string"},
        },
    }
    form = SchemaObjectForm.build(
        schema_root=schema,
        object_schema=schema,
        effective_values={"script": "sase_lint"},
        target_values={"script": "sase_lint"},
    )
    header, description, values = detail_dock_lines(
        form.field("script"),
        target="user",
        vim_mode="INSERT",
    )
    assert header == "script *  string  INSERT"
    assert description == "Executable to run."
    assert 'Layer(user) "sase_lint"' in values
    assert 'Inherits "—"' in values

    _header, missing_description, missing_values = detail_dock_lines(
        form.field("optional"),
        target="user",
    )
    assert missing_description == "No description available."
    assert missing_values == 'Effective "—"  Layer(user) "—"  Inherits "—"'


def test_status_and_hints_are_mode_and_stage_aware() -> None:
    form = _state_form()
    assert status_line_text(form.field("invalid")) == "! 'oops' is not an integer"
    assert status_line_text(None, error="nothing changed") == "! nothing changed"
    assert hint_text(
        mode="browse",
        stage="edit",
        running=False,
    ) == (
        "↑↓/jk move · ⏎/i edit · space toggle · ^R inherit · "
        "1-9 scope · ^S preview & save · q quit · esc"
    )
    assert hint_text(
        mode="browse",
        stage="edit",
        running=False,
        narrow=True,
    ) == ("↑↓ move · ⏎/i edit · space toggle · 1-9 scope · ^S save · q quit · esc")
    assert hint_text(
        mode="cell",
        stage="edit",
        running=False,
    ) == ("tab next · shift+tab previous · esc normal/browse · ^R inherit · ^S preview")
    assert (
        hint_text(
            mode="cell",
            stage="edit",
            running=False,
            narrow=True,
        )
        == "tab next · ⇧tab prev · esc normal/browse · ^S preview"
    )
    assert hint_text(
        mode="browse",
        stage="preview",
        running=True,
    ) == (
        "↑↓ scroll · ^D/^U page · ⏎ save & restart · ^O save only · q quit · esc back"
    )
    assert (
        hint_text(
            mode="browse",
            stage="preview",
            running=True,
            narrow=True,
        )
        == "↑↓ scroll · ^D/^U page · ⏎ save & restart · q quit · esc back"
    )
    assert (
        hint_text(
            mode="browse",
            stage="preview",
            running=True,
            busy=True,
        )
        == "Working…"
    )
