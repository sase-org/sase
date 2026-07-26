"""Tests for unified raw-placeholder and declared-input prompt plans."""

from __future__ import annotations

import pytest

from sase.agent.prompt_inputs import PromptInputError
from sase.agent.prompt_placeholder_inputs import (
    PromptInputValues,
    apply_prompt_input_values,
    build_prompt_input_plan,
)


def test_frontmatter_is_excluded_from_placeholder_scan() -> None:
    prompt = "---\ndescription: mention <name>\n---\nUse <task>."

    plan = build_prompt_input_plan(prompt)

    assert [field.text for field in plan.placeholders] == ["task"]
    assert plan.declared is None
    assert plan.needs_collection is True


def test_placeholder_and_declared_input_share_one_plan_and_apply_order() -> None:
    prompt = (
        "---\n"
        "input:\n"
        "  service: word\n"
        "  retries:\n"
        "    type: int\n"
        "    default: 2\n"
        "---\n"
        "Refactor <the plan> for {{ service }} with {{ retries }} retries."
    )

    plan = build_prompt_input_plan(prompt)

    assert [field.text for field in plan.placeholders] == ["the plan"]
    assert plan.declared is not None
    assert [arg.name for arg in plan.declared.inputs] == ["service", "retries"]
    assert [arg.name for arg in plan.declared.required] == ["service"]
    assert plan.needs_collection is True

    out = apply_prompt_input_values(
        prompt,
        PromptInputValues(
            placeholders={"the plan": "routing cleanup"},
            declared={"service": "billing"},
        ),
    )

    assert out == "Refactor routing cleanup for billing with 2 retries."


def test_literal_marked_placeholder_survives_when_omitted_from_values() -> None:
    prompt = "Refactor <the plan> and keep `<div>` literal."

    out = apply_prompt_input_values(
        prompt,
        PromptInputValues(placeholders={}, declared={}),
    )

    assert out == prompt


def test_placeholder_value_is_not_jinja_rendered_without_declared_inputs() -> None:
    prompt = "Write <template>."

    out = apply_prompt_input_values(
        prompt,
        PromptInputValues(placeholders={"template": "{{ x }}"}, declared={}),
    )

    assert out == "Write {{ x }}."


def test_multi_segment_prompt_collects_once_and_substitutes_every_segment() -> None:
    prompt = "First <target>.\n---\nSecond <target>."

    plan = build_prompt_input_plan(prompt)
    out = apply_prompt_input_values(
        prompt,
        PromptInputValues(placeholders={"target": "auth"}, declared={}),
    )

    assert [(field.text, field.occurrences) for field in plan.placeholders] == [
        ("target", 2)
    ]
    assert out == "First auth.\n---\nSecond auth."


def test_optional_declared_inputs_do_not_require_collection() -> None:
    prompt = "---\ninput:\n  dry_run:\n    type: bool\n    default: false\n---\nrun"

    plan = build_prompt_input_plan(prompt)

    assert plan.placeholders == ()
    assert plan.declared is not None
    assert plan.declared.has_required is False
    assert plan.needs_collection is False


def test_apply_reraises_prompt_input_error_unchanged() -> None:
    prompt = "---\ninput:\n  retries: int\n---\nUse {{ retries }}"

    with pytest.raises(PromptInputError, match="expects int"):
        apply_prompt_input_values(
            prompt,
            PromptInputValues(placeholders={}, declared={"retries": "many"}),
        )
