"""Repeatable xprompt input contract coverage."""

from __future__ import annotations

import pytest
from unittest.mock import patch

from sase.xprompt._catalog_format import format_inputs
from sase.xprompt._catalog_structured import structured_inputs
from sase.xprompt._jinja import validate_and_convert_args
from sase.xprompt._parsing import parse_workflow_reference
from sase.xprompt.input_binding import InputBindingError, bind_input_args
from sase.xprompt.loader_parsing import (
    parse_inputs_from_front_matter,
    parse_shortform_inputs,
)
from sase.xprompt.models import (
    InputArg,
    InputType,
    XPrompt,
    XPromptValidationError,
)
from sase.xprompt.processor import process_xprompt_references


def _repeatable(
    *, type_: InputType = InputType.AGENT, default: object = None
) -> InputArg:
    return InputArg(
        name="names",
        type=type_,
        default=default,
        repeatable=True,
    )


def test_shortform_and_longform_load_repeatable_metadata() -> None:
    short = parse_shortform_inputs(
        {"names": {"type": "agent", "default": None, "repeatable": True}}
    )
    long = parse_inputs_from_front_matter(
        [
            {
                "name": "names",
                "type": "agent",
                "default": None,
                "repeatable": True,
            }
        ]
    )

    assert short[0].repeatable is True
    assert long[0].repeatable is True


def test_repeatable_input_must_be_final() -> None:
    with pytest.raises(XPromptValidationError, match="final"):
        parse_shortform_inputs(
            {
                "names": {"type": "agent", "repeatable": True},
                "mode": "word",
            }
        )


def test_repeatable_tail_consumes_and_validates_every_positional() -> None:
    inputs = [
        InputArg(name="mode", type=InputType.WORD),
        _repeatable(type_=InputType.INT),
    ]

    bound = bind_input_args(inputs, ["fast", "1", "2", "3"], {})

    assert bound.positional == ["fast", 1, 2, 3]
    assert bound.values == {"mode": "fast", "names": [1, 2, 3]}
    with pytest.raises(InputBindingError, match="expects int"):
        bind_input_args(inputs, ["fast", "1", "bad"], {})


def test_repeatable_named_value_keeps_named_over_positional_precedence() -> None:
    bound = bind_input_args(
        [_repeatable()], ["planner", "coder"], {"names": "reviewer"}
    )

    assert bound.positional == ["planner", "coder"]
    assert bound.values["names"] == ["reviewer"]


def test_repeatable_bare_call_uses_null_default() -> None:
    bound = bind_input_args([_repeatable()], [], {})

    assert bound.values == {"names": None}


def test_repeatable_agent_rejects_empty_elements_in_both_call_syntaxes() -> None:
    xprompt = XPrompt(name="merge", content="{{ names }}", inputs=[_repeatable()])
    _, paren_values, _ = parse_workflow_reference("merge(planner,,coder)")

    assert paren_values == ["planner", "", "coder"]
    with pytest.raises(InputBindingError, match="non-empty word"):
        bind_input_args(xprompt.inputs, paren_values, {})
    with pytest.raises(InputBindingError, match="non-empty word"):
        bind_input_args(xprompt.inputs, "planner,,coder".split(","), {})

    with patch(
        "sase.xprompt.processor.get_all_xprompts", return_value={"merge": xprompt}
    ):
        with pytest.raises(SystemExit):
            process_xprompt_references("#merge:planner,")


def test_non_repeatable_inputs_still_reject_surplus_positionals() -> None:
    with pytest.raises(InputBindingError, match="Too many positional"):
        bind_input_args([InputArg(name="one")], ["first", "second"], {})


def test_jinja_binding_exposes_repeatable_input_as_ordered_list() -> None:
    xprompt = XPrompt(
        name="merge",
        content="{{ names | join(' > ') }}",
        inputs=[_repeatable()],
    )

    positional, values = validate_and_convert_args(xprompt, ["planner", "coder"], {})

    assert positional == ["planner", "coder"]
    assert values["names"] == ["planner", "coder"]


def test_catalog_projection_carries_repeatable_and_signature_hint() -> None:
    inputs = [_repeatable()]

    assert structured_inputs(inputs)[0].repeatable is True
    assert format_inputs(inputs) == "(names…?: agent)"
