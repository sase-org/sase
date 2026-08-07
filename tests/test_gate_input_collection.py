"""Coverage for the shared per-selection input-collection helper."""

from __future__ import annotations

import pytest

from sase.notification_gates.input_collection import (
    coerce_field_text,
    collected_input_fields,
    input_arg_for_field,
    option_inputs_from_values,
)
from sase.notification_gates.model_inputs import GateInputField
from sase.notification_gates.model_options import GateCommand, GateOption
from sase.notification_gates.model_validation import GateError
from sase.xprompt.models import UNSET, InputChoice, InputType, XPromptValidationError


def _option(option_id: str, *inputs: GateInputField) -> GateOption:
    return GateOption(
        id=option_id,
        label=option_id.title(),
        command=GateCommand(argv=(f"commands/{option_id}",)),
        inputs=inputs,
    )


def test_collected_input_fields_dedupes_by_id_in_first_declared_order() -> None:
    shared = GateInputField(id="reason", label="Reason", type=InputType.LINE)
    only_b = GateInputField(id="detail", label="Detail", type=InputType.TEXT)
    option_a = _option("approve", shared)
    option_b = _option("audit", shared, only_b)

    fields = collected_input_fields((option_a, option_b))

    assert [field.id for field in fields] == ["reason", "detail"]
    assert fields[0] is shared


def test_collected_input_fields_raises_on_conflicting_declarations() -> None:
    option_a = _option(
        "approve", GateInputField(id="reason", label="Reason", type=InputType.LINE)
    )
    option_b = _option(
        "audit", GateInputField(id="reason", label="Reason", type=InputType.TEXT)
    )

    with pytest.raises(GateError) as excinfo:
        collected_input_fields((option_a, option_b))

    assert excinfo.value.code == "conflicting_input_field"
    assert "approve" in str(excinfo.value)
    assert "audit" in str(excinfo.value)


def test_collected_input_fields_allows_differing_presentation_only() -> None:
    option_a = _option(
        "approve",
        GateInputField(
            id="reason", label="Reason A", type=InputType.LINE, required=True
        ),
    )
    option_b = _option(
        "audit",
        GateInputField(
            id="reason", label="Reason B", type=InputType.LINE, required=False
        ),
    )

    fields = collected_input_fields((option_a, option_b))

    assert len(fields) == 1
    assert fields[0].label == "Reason A"


def test_input_arg_for_field_maps_required_to_unset_default() -> None:
    required = GateInputField(
        id="reason", label="Reason", type=InputType.LINE, required=True
    )
    optional = GateInputField(
        id="tag", label="Tag", type=InputType.LINE, required=False, default="x"
    )

    assert input_arg_for_field(required).default is UNSET
    assert input_arg_for_field(optional).default == "x"


def test_coerce_field_text_converts_scalar_field() -> None:
    field = GateInputField(id="count", label="Count", type=InputType.INT)

    assert coerce_field_text(field, "3") == 3


def test_coerce_field_text_repeatable_splits_newlines_and_drops_blanks() -> None:
    field = GateInputField(
        id="tags", label="Tags", type=InputType.WORD, repeatable=True
    )

    assert coerce_field_text(field, "alpha\n\nbeta\n") == ["alpha", "beta"]


def test_coerce_field_text_enum_rejection_lists_allowed_values() -> None:
    field = GateInputField(
        id="mode",
        label="Mode",
        type=InputType.ENUM,
        choices=(InputChoice(value="fast"), InputChoice(value="slow")),
    )

    with pytest.raises(XPromptValidationError) as excinfo:
        coerce_field_text(field, "turbo")

    assert "fast" in str(excinfo.value)
    assert "slow" in str(excinfo.value)


def test_option_inputs_from_values_gives_each_option_only_its_declared_ids() -> None:
    option_a = _option(
        "approve", GateInputField(id="reason", label="Reason", type=InputType.LINE)
    )
    option_b = _option(
        "audit", GateInputField(id="detail", label="Detail", type=InputType.TEXT)
    )
    values = {"reason": "looks good", "detail": "checked twice"}

    result = option_inputs_from_values((option_a, option_b), values)

    assert result == {
        "approve": {"reason": "looks good"},
        "audit": {"detail": "checked twice"},
    }


def test_option_inputs_from_values_option_declaring_nothing_maps_to_empty() -> None:
    option = _option("cancel")

    result = option_inputs_from_values((option,), {"reason": "unused"})

    assert result == {"cancel": {}}
