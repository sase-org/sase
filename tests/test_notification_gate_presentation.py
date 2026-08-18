"""Coverage for gate presentation field normalization and custom-kind requirements."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.notification_gates.models import GateError
from sase.notification_gates.presentation import (
    GATE_CHIP_COLOR_ACTION_DATA_KEY,
    GATE_CHIP_GLYPH_ACTION_DATA_KEY,
    GATE_CHIP_LABEL_ACTION_DATA_KEY,
    GATE_TITLE_ACTION_DATA_KEY,
    RESERVED_GATE_PANELS,
    GateChip,
    gate_chip_from_action_data,
    normalize_gate_chip,
    normalize_gate_panel_icon,
    normalize_gate_title,
)
from sase.notification_gates.service import create_gate
from sase.notifications.store import load_notifications

from tests._notification_gates_fixtures import custom_gate_spec, gate_spec


def test_normalize_gate_title_accepts_none() -> None:
    assert normalize_gate_title(None) is None


def test_normalize_gate_title_strips_whitespace() -> None:
    assert normalize_gate_title("  Restart the service  ") == "Restart the service"


@pytest.mark.parametrize(
    "value",
    ["", "   ", "x" * 121, "line one\nline two", "bad\x00title", 7],
)
def test_normalize_gate_title_rejects_invalid_values(value: object) -> None:
    with pytest.raises(GateError) as exc_info:
        normalize_gate_title(value)
    assert exc_info.value.code == "invalid_presentation"
    assert exc_info.value.target == "presentation.title"


def test_normalize_gate_panel_icon_accepts_none() -> None:
    assert normalize_gate_panel_icon(None) is None


@pytest.mark.parametrize("value", ["◈", "⚑", "🚀", "#"])
def test_normalize_gate_panel_icon_accepts_one_glyph(value: str) -> None:
    assert normalize_gate_panel_icon(value) == value


@pytest.mark.parametrize(
    "value",
    ["", "   ", " ◈ ", "◈◆", "beads", "\x00", "x" * 33, 7],
)
def test_normalize_gate_panel_icon_rejects_invalid_values(value: object) -> None:
    with pytest.raises(GateError) as exc_info:
        normalize_gate_panel_icon(value)
    assert exc_info.value.code == "invalid_presentation"
    assert exc_info.value.target == "presentation.panel_icon"


def test_normalize_gate_chip_accepts_none() -> None:
    assert normalize_gate_chip(None) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"glyph": "≈", "label": "flake"}, GateChip("≈", "flake")),
        ({"glyph": "≈", "label": "  flake  "}, GateChip("≈", "flake")),
        (
            {"glyph": "≈", "label": "flake", "color": " #AF87FF "},
            GateChip("≈", "flake", "#AF87FF"),
        ),
        (
            {"glyph": "≈", "label": "flake", "color": None},
            GateChip("≈", "flake"),
        ),
        (
            {"glyph": "🚀", "label": "x" * 32, "color": "#00ff00"},
            GateChip("🚀", "x" * 32, "#00ff00"),
        ),
        (
            {"glyph": "#", "label": "ok", "ignored": True},
            GateChip("#", "ok"),
        ),
    ],
)
def test_normalize_gate_chip_accepts_legal_forms(
    value: object, expected: GateChip
) -> None:
    assert normalize_gate_chip(value) == expected


@pytest.mark.parametrize(
    ("value", "fragment"),
    [
        (7, "must be an object"),
        ("flake", "must be an object"),
        ([], "must be an object"),
        ({}, "glyph"),
        ({"label": "flake"}, "glyph"),
        ({"glyph": "≈"}, "label"),
        ({"glyph": "", "label": "flake"}, "glyph"),
        ({"glyph": " ≈ ", "label": "flake"}, "glyph"),
        ({"glyph": "≈≈", "label": "flake"}, "glyph"),
        ({"glyph": "ab", "label": "flake"}, "glyph"),
        ({"glyph": 7, "label": "flake"}, "glyph"),
        ({"glyph": "≈", "label": ""}, "label"),
        ({"glyph": "≈", "label": "   "}, "label"),
        ({"glyph": "≈", "label": "x" * 33}, "label"),
        ({"glyph": "≈", "label": "line\nbreak"}, "label"),
        ({"glyph": "≈", "label": "bad\x00lab"}, "label"),
        ({"glyph": "≈", "label": 7}, "label"),
        ({"glyph": "≈", "label": "flake", "color": "red"}, "color"),
        ({"glyph": "≈", "label": "flake", "color": "#FFF"}, "color"),
        ({"glyph": "≈", "label": "flake", "color": "#GGGGGG"}, "color"),
        ({"glyph": "≈", "label": "flake", "color": 7}, "color"),
    ],
)
def test_normalize_gate_chip_rejects_invalid_values(
    value: object, fragment: str
) -> None:
    with pytest.raises(GateError) as exc_info:
        normalize_gate_chip(value)
    assert exc_info.value.code == "invalid_presentation"
    assert exc_info.value.target == "presentation.chip"
    assert fragment in str(exc_info.value)
    assert repr(value) in str(exc_info.value)


@pytest.mark.parametrize(
    ("action_data", "expected"),
    [
        (None, None),
        ("not-a-map", None),
        (7, None),
        ([], None),
        ({}, None),
        ({GATE_CHIP_GLYPH_ACTION_DATA_KEY: "≈"}, None),
        ({GATE_CHIP_LABEL_ACTION_DATA_KEY: "flake"}, None),
        (
            {
                GATE_CHIP_GLYPH_ACTION_DATA_KEY: "",
                GATE_CHIP_LABEL_ACTION_DATA_KEY: "flake",
            },
            None,
        ),
        (
            {
                GATE_CHIP_GLYPH_ACTION_DATA_KEY: "≈",
                GATE_CHIP_LABEL_ACTION_DATA_KEY: "",
            },
            None,
        ),
        (
            {
                GATE_CHIP_GLYPH_ACTION_DATA_KEY: "≈≈",
                GATE_CHIP_LABEL_ACTION_DATA_KEY: "flake",
            },
            None,
        ),
        (
            {
                GATE_CHIP_GLYPH_ACTION_DATA_KEY: " ≈ ",
                GATE_CHIP_LABEL_ACTION_DATA_KEY: "flake",
            },
            None,
        ),
        (
            {
                GATE_CHIP_GLYPH_ACTION_DATA_KEY: "≈",
                GATE_CHIP_LABEL_ACTION_DATA_KEY: "line\nbreak",
            },
            None,
        ),
        (
            {
                GATE_CHIP_GLYPH_ACTION_DATA_KEY: "≈",
                GATE_CHIP_LABEL_ACTION_DATA_KEY: "bad\x00lab",
            },
            None,
        ),
        (
            {
                GATE_CHIP_GLYPH_ACTION_DATA_KEY: "≈",
                GATE_CHIP_LABEL_ACTION_DATA_KEY: "x" * 33,
            },
            None,
        ),
        (
            {
                GATE_CHIP_GLYPH_ACTION_DATA_KEY: 7,
                GATE_CHIP_LABEL_ACTION_DATA_KEY: "flake",
            },
            None,
        ),
        (
            {
                GATE_CHIP_GLYPH_ACTION_DATA_KEY: "≈",
                GATE_CHIP_LABEL_ACTION_DATA_KEY: 7,
            },
            None,
        ),
        (
            {
                GATE_CHIP_GLYPH_ACTION_DATA_KEY: "≈",
                GATE_CHIP_LABEL_ACTION_DATA_KEY: "flake",
            },
            GateChip("≈", "flake"),
        ),
        (
            {
                GATE_CHIP_GLYPH_ACTION_DATA_KEY: "≈",
                GATE_CHIP_LABEL_ACTION_DATA_KEY: "  flake  ",
            },
            GateChip("≈", "flake"),
        ),
        (
            {
                GATE_CHIP_GLYPH_ACTION_DATA_KEY: "≈",
                GATE_CHIP_LABEL_ACTION_DATA_KEY: "flake",
                GATE_CHIP_COLOR_ACTION_DATA_KEY: "#AF87FF",
            },
            GateChip("≈", "flake", "#AF87FF"),
        ),
        (
            {
                GATE_CHIP_GLYPH_ACTION_DATA_KEY: "≈",
                GATE_CHIP_LABEL_ACTION_DATA_KEY: "flake",
                GATE_CHIP_COLOR_ACTION_DATA_KEY: " #00ff00 ",
            },
            GateChip("≈", "flake", "#00ff00"),
        ),
        (
            {
                GATE_CHIP_GLYPH_ACTION_DATA_KEY: "≈",
                GATE_CHIP_LABEL_ACTION_DATA_KEY: "flake",
                GATE_CHIP_COLOR_ACTION_DATA_KEY: "red",
            },
            GateChip("≈", "flake"),
        ),
        (
            {
                GATE_CHIP_GLYPH_ACTION_DATA_KEY: "≈",
                GATE_CHIP_LABEL_ACTION_DATA_KEY: "flake",
                GATE_CHIP_COLOR_ACTION_DATA_KEY: "#FFF",
            },
            GateChip("≈", "flake"),
        ),
        (
            {
                GATE_CHIP_GLYPH_ACTION_DATA_KEY: "≈",
                GATE_CHIP_LABEL_ACTION_DATA_KEY: "flake",
                GATE_CHIP_COLOR_ACTION_DATA_KEY: 7,
            },
            GateChip("≈", "flake"),
        ),
        (
            {
                GATE_CHIP_GLYPH_ACTION_DATA_KEY: "≈",
                GATE_CHIP_LABEL_ACTION_DATA_KEY: "flake",
                GATE_CHIP_COLOR_ACTION_DATA_KEY: "",
            },
            GateChip("≈", "flake"),
        ),
    ],
)
def test_gate_chip_from_action_data_is_tolerant(
    action_data: object, expected: GateChip | None
) -> None:
    assert gate_chip_from_action_data(action_data) == expected


def test_gate_title_is_projected_into_action_data(gate_home: Path) -> None:
    del gate_home
    result = create_gate(custom_gate_spec())
    [notification] = load_notifications(include_dismissed=True)
    assert (
        notification.action_data[GATE_TITLE_ACTION_DATA_KEY] == "Confirm guarded work"
    )
    assert result.notification_id == notification.id


def test_gate_title_action_data_cannot_bypass_normalization(gate_home: Path) -> None:
    del gate_home
    spec = custom_gate_spec()
    presentation = spec["presentation"]
    assert isinstance(presentation, dict)
    presentation["action_data"] = {"gate_title": "forged"}

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)

    assert exc_info.value.code == "reserved_action_data"
    assert exc_info.value.target == "presentation.action_data"
    assert "gate_title" in str(exc_info.value)


def test_gates_panel_name_is_reserved(gate_home: Path) -> None:
    del gate_home
    assert "gates" in RESERVED_GATE_PANELS
    spec = gate_spec()
    presentation = spec["presentation"]
    assert isinstance(presentation, dict)
    presentation["panel"] = "gates"

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)

    assert exc_info.value.code == "invalid_presentation"
    assert exc_info.value.target == "presentation.panel"
    assert "gates" in str(exc_info.value)


@pytest.mark.parametrize(
    ("field", "mutate"),
    [
        ("title", lambda presentation: presentation.pop("title", None)),
        ("icon", lambda presentation: presentation.pop("icon", None)),
        ("notes", lambda presentation: presentation.__setitem__("notes", [])),
        ("notes", lambda presentation: presentation.__setitem__("notes", ["   "])),
    ],
)
def test_custom_gate_missing_required_presentation_field_fails(
    gate_home: Path, field: str, mutate: object
) -> None:
    del gate_home
    spec = custom_gate_spec()
    presentation = spec["presentation"]
    assert isinstance(presentation, dict)
    mutate(presentation)  # type: ignore[operator]

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)

    assert exc_info.value.code == "missing_presentation"
    assert exc_info.value.target == f"presentation.{field}"


def test_hitl_gate_does_not_require_title_icon_or_notes(gate_home: Path) -> None:
    del gate_home
    spec = gate_spec(kind="hitl")
    presentation = spec["presentation"]
    assert isinstance(presentation, dict)
    presentation.pop("title", None)
    presentation.pop("icon", None)
    presentation["notes"] = []

    result = create_gate(spec)

    assert result.kind == "hitl"
