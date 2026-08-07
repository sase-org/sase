"""Coverage for gate presentation title normalization and custom-kind requirements."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.notification_gates.models import GateError
from sase.notification_gates.presentation import (
    GATE_TITLE_ACTION_DATA_KEY,
    RESERVED_GATE_PANELS,
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
