"""Tests for xprompt.loader parsing functions."""

import pytest

from sase.xprompt.loader_parsing import (
    _parse_input_choices,
    _parse_shortform_output,
    parse_inputs_from_front_matter,
    parse_xprompt_entries,
    parse_yaml_front_matter,
)
from sase.xprompt.models import UNSET, InputChoice, InputType, XPromptValidationError

# Tests for parse_yaml_front_matter


def testparse_yaml_front_matter_opening_without_closing() -> None:
    """Test content with opening --- but no closing ---."""
    content = """---
name: test
No closing marker"""
    front_matter, body = parse_yaml_front_matter(content)

    assert front_matter is None
    assert body == content


def testparse_yaml_front_matter_empty_front_matter() -> None:
    """Test empty front matter section."""
    content = """---
---
Body here"""
    front_matter, body = parse_yaml_front_matter(content)

    assert front_matter == {}
    assert body == "Body here"


# Tests for parse_inputs_from_front_matter


def test_parse_inputs_empty_list() -> None:
    """Test with empty list."""
    inputs = parse_inputs_from_front_matter([])
    assert inputs == []


def test_parse_inputs_skips_invalid_items() -> None:
    """Test that items without name are skipped."""
    input_list = [
        {"name": "valid"},
        {"type": "int"},  # Missing name
        "not a dict",  # Wrong type (intentionally testing edge case)
        {"name": "also_valid"},
    ]
    inputs = parse_inputs_from_front_matter(input_list)  # type: ignore[arg-type]

    assert len(inputs) == 2
    assert inputs[0].name == "valid"
    assert inputs[1].name == "also_valid"


def test_parse_inputs_longform_description() -> None:
    inputs = parse_inputs_from_front_matter(
        [
            {
                "name": "diff_path",
                "type": "path",
                "description": "Diff file to review.",
            }
        ]
    )

    assert len(inputs) == 1
    assert inputs[0].name == "diff_path"
    assert inputs[0].type is InputType.PATH
    assert inputs[0].default is UNSET
    assert inputs[0].description == "Diff file to review."


def test_parse_inputs_nested_shortform_description() -> None:
    inputs = parse_inputs_from_front_matter(
        {
            "max_retries": {
                "type": "int",
                "default": 3,
                "description": "Maximum retry attempts.",
            }
        }
    )

    assert len(inputs) == 1
    assert inputs[0].name == "max_retries"
    assert inputs[0].type is InputType.INT
    assert inputs[0].default == 3
    assert inputs[0].description == "Maximum retry attempts."


def test_parse_inputs_simple_shorthand_has_no_description() -> None:
    inputs = parse_inputs_from_front_matter({"diff_path": "path"})

    assert len(inputs) == 1
    assert inputs[0].name == "diff_path"
    assert inputs[0].type is InputType.PATH
    assert inputs[0].description is None


# Tests for enum choices


def test_parse_inputs_shortform_enum_scalar_choices() -> None:
    inputs = parse_inputs_from_front_matter(
        {"mode": {"type": "enum", "choices": ["fast", "slow"]}}
    )

    assert len(inputs) == 1
    assert inputs[0].type is InputType.ENUM
    assert inputs[0].choices == (
        InputChoice(value="fast"),
        InputChoice(value="slow"),
    )


def test_parse_inputs_shortform_enum_mapping_choices() -> None:
    inputs = parse_inputs_from_front_matter(
        {
            "mode": {
                "type": "enum",
                "choices": [
                    {"value": "fast", "label": "Fast mode"},
                    {"value": "slow", "label": "Slow mode"},
                ],
            }
        }
    )

    assert len(inputs) == 1
    assert inputs[0].choices == (
        InputChoice(value="fast", label="Fast mode"),
        InputChoice(value="slow", label="Slow mode"),
    )


def test_parse_inputs_longform_enum_choices() -> None:
    inputs = parse_inputs_from_front_matter(
        [
            {
                "name": "mode",
                "type": "enum",
                "choices": ["fast", {"value": "slow", "label": "Slow mode"}],
            }
        ]
    )

    assert len(inputs) == 1
    assert inputs[0].type is InputType.ENUM
    assert inputs[0].choices == (
        InputChoice(value="fast"),
        InputChoice(value="slow", label="Slow mode"),
    )


def test_parse_inputs_enum_without_choices_raises() -> None:
    with pytest.raises(XPromptValidationError):
        parse_inputs_from_front_matter({"mode": {"type": "enum"}})


def test_parse_inputs_choices_on_non_enum_type_raises() -> None:
    with pytest.raises(XPromptValidationError):
        parse_inputs_from_front_matter(
            {"mode": {"type": "word", "choices": ["fast", "slow"]}}
        )


def test_parse_inputs_duplicate_choice_values_raises() -> None:
    with pytest.raises(XPromptValidationError):
        parse_inputs_from_front_matter(
            {"mode": {"type": "enum", "choices": ["fast", "fast"]}}
        )


def test_parse_input_choices_rejects_non_list() -> None:
    with pytest.raises(XPromptValidationError):
        _parse_input_choices("fast", "mode")


def test_parse_input_choices_rejects_empty_list() -> None:
    with pytest.raises(XPromptValidationError):
        _parse_input_choices([], "mode")


def test_parse_input_choices_rejects_mapping_without_value() -> None:
    with pytest.raises(XPromptValidationError):
        _parse_input_choices([{"label": "Fast mode"}], "mode")


def test_parse_input_choices_rejects_bad_item_shape() -> None:
    with pytest.raises(XPromptValidationError):
        _parse_input_choices([["fast"]], "mode")


# Tests for _parse_shortform_output


def test_shortform_output_spec_field_with_empty_string_default_is_nullable() -> None:
    """Field with default: '' should produce nullable type."""
    spec = _parse_shortform_output(
        [{"name": "word", "parent": {"type": "word", "default": ""}}]
    )
    props = spec.schema["items"]["properties"]
    assert props["parent"]["type"] == ["word", "null"]
    assert props["parent"]["default"] == ""


def test_shortform_output_spec_field_with_none_default_is_nullable() -> None:
    """Field with default: None (null) should produce nullable type."""
    spec = _parse_shortform_output(
        [{"name": "word", "parent": {"type": "word", "default": None}}]
    )
    props = spec.schema["items"]["properties"]
    assert props["parent"]["type"] == ["word", "null"]
    assert "default" not in props["parent"]


def test_shortform_output_spec_field_without_default_not_nullable() -> None:
    """Field without a default should NOT be nullable and should be required."""
    spec = _parse_shortform_output([{"name": "word", "parent": "word"}])
    props = spec.schema["items"]["properties"]
    assert props["parent"]["type"] == "word"
    assert "parent" in spec.schema["items"]["required"]


# Tests for skill and description parsing from frontmatter


def test_parse_yaml_front_matter_skill_true() -> None:
    """Test parsing skill: true from front matter."""
    content = """---
name: my_skill
description: A test skill
skill: true
---
Skill content here"""
    front_matter, body = parse_yaml_front_matter(content)

    assert front_matter is not None
    assert front_matter["skill"] is True
    assert front_matter["description"] == "A test skill"
    assert body == "Skill content here"


def test_parse_yaml_front_matter_skill_provider_list() -> None:
    """Test parsing skill with a list of providers from front matter."""
    content = """---
name: my_skill
skill: [claude, gemini]
---
Skill content"""
    front_matter, _ = parse_yaml_front_matter(content)

    assert front_matter is not None
    assert front_matter["skill"] == ["claude", "gemini"]


# Tests for skill and description in parse_xprompt_entries


def test_parse_xprompt_entries_skill_and_description() -> None:
    """Test parsing skill and description from structured dict format."""
    entries = {
        "my_skill": {
            "content": "Do the thing",
            "description": "A helpful skill",
            "skill": True,
        }
    }
    result = parse_xprompt_entries(entries, "test")

    xp = result["my_skill"]
    assert xp.description == "A helpful skill"
    assert xp.skill is True


def test_parse_xprompt_entries_skill_provider_list() -> None:
    """Test parsing skill with provider list from structured dict format."""
    entries = {
        "hg_commit": {
            "content": "Commit with a VCS provider",
            "skill": ["gemini"],
        }
    }
    result = parse_xprompt_entries(entries, "test")

    xp = result["hg_commit"]
    assert xp.skill == ["gemini"]
    assert xp.description is None


def test_parse_xprompt_entries_simple_string_has_no_skill() -> None:
    """Test that simple string xprompts have None for skill and description."""
    entries = {"simple": "Just a string"}
    result = parse_xprompt_entries(entries, "test")

    xp = result["simple"]
    assert xp.skill is None
    assert xp.description is None


# Tests for log_skill_use in parse_xprompt_entries


def test_parse_xprompt_entries_log_skill_use_false() -> None:
    """Structured config entries can disable the generated audit directive."""
    entries = {
        "quiet_skill": {
            "content": "Do the thing",
            "skill": True,
            "log_skill_use": False,
        }
    }
    result = parse_xprompt_entries(entries, "test")

    assert result["quiet_skill"].log_skill_use is False


def test_parse_xprompt_entries_log_skill_use_defaults_true() -> None:
    """Structured config entries default log_skill_use to True when absent."""
    entries = {
        "loud_skill": {
            "content": "Do the thing",
            "skill": True,
        }
    }
    result = parse_xprompt_entries(entries, "test")

    assert result["loud_skill"].log_skill_use is True


def test_parse_xprompt_entries_simple_string_log_skill_use_true() -> None:
    """Simple string xprompts keep the default log_skill_use of True."""
    entries = {"simple": "Just a string"}
    result = parse_xprompt_entries(entries, "test")

    assert result["simple"].log_skill_use is True
