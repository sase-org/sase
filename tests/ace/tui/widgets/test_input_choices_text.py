"""Unit tests for the shared lossless choices-text helper."""

from __future__ import annotations

import pytest

from sase.ace.tui.widgets._input_choices_text import (
    format_choices_text,
    parse_choices_text,
)
from sase.macro.models import InputChoice, MacroValidationError


def test_parse_flow_list_with_labels() -> None:
    choices = parse_choices_text(
        "[wip, draft, {value: ready, label: Ready}]", name="status"
    )
    assert choices == (
        InputChoice(value="wip"),
        InputChoice(value="draft"),
        InputChoice(value="ready", label="Ready"),
    )


@pytest.mark.parametrize(
    "text",
    [
        "[a, a]",
        "- yes",
        "[1, a]",
        "- null",
        '- ""',
        "[a, ' ']",
        "[]",
        "",
        "just-a-string",
    ],
)
def test_parse_surfaces_every_rust_issue_class(text: str) -> None:
    with pytest.raises(MacroValidationError):
        parse_choices_text(text, name="status")


def test_parse_duplicate_names_the_value() -> None:
    with pytest.raises(MacroValidationError, match="declared twice"):
        parse_choices_text("[a, a]", name="status")


def test_round_trip_flow_and_block() -> None:
    choices = (
        InputChoice(value="on"),
        InputChoice(value="off"),
        InputChoice(value="yes", label="Yes"),
        InputChoice(value="héllo", description="greeting"),
        InputChoice(value="ready", label="Ready", description="Ship it"),
    )
    for flow in (True, False):
        text = format_choices_text(choices, flow=flow)
        assert parse_choices_text(text, name="status") == choices


def test_format_quotes_yaml_booleans() -> None:
    text = format_choices_text((InputChoice(value="on"),), flow=True)
    assert "'on'" in text
    assert parse_choices_text(text, name="status") == (InputChoice(value="on"),)
