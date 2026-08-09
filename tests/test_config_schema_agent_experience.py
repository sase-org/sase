"""Config schema coverage for xprompts, memory, hooks, and ACE settings."""

from __future__ import annotations

import pytest
from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError

from tests._config_schema_helpers import format_schema_error, schema


def test_config_schema_accepts_xprompt_input_descriptions() -> None:
    public_schema = schema()
    config = {
        "xprompts": {
            "review": {
                "description": "Review a selected path.",
                "input": {
                    "path": {
                        "type": "path",
                        "description": "Path to review.",
                    }
                },
                "content": "Review {{ path }}",
            },
            "ask": {
                "input": [
                    {
                        "name": "prompt",
                        "type": "text",
                        "description": "User request to answer.",
                    }
                ],
                "content": "Answer {{ prompt }}",
            },
        }
    }

    errors = sorted(
        Draft7Validator(public_schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert errors == [], "\n".join(format_schema_error(error) for error in errors)


def test_config_schema_accepts_xprompt_log_skill_use() -> None:
    public_schema = schema()
    config = {
        "xprompts": {
            "quiet_skill": {
                "description": "A skill that does not log its own use.",
                "skill": True,
                "log_skill_use": False,
                "content": "Do the thing",
            }
        }
    }

    errors = sorted(
        Draft7Validator(public_schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert errors == [], "\n".join(format_schema_error(error) for error in errors)


def test_config_schema_rejects_retired_memory_keywords() -> None:
    with pytest.raises(ValidationError):
        Draft7Validator(schema()).validate(
            {
                "xprompts": {
                    "legacy_memory": {
                        "content": "Legacy memory prompt",
                        "keywords": ["memory"],
                    }
                }
            }
        )


def test_config_schema_accepts_amd_h1_title_string_or_null() -> None:
    public_schema = schema()

    for config in (
        {"memory": {"h1_title": None}},
        {"memory": {"h1_title": "Agent Instructions"}},
    ):
        errors = sorted(
            Draft7Validator(public_schema).iter_errors(config),
            key=lambda error: list(error.absolute_path),
        )

        assert errors == [], "\n".join(format_schema_error(error) for error in errors)

    with pytest.raises(ValidationError):
        Draft7Validator(public_schema).validate({"memory": {"unknown": True}})


def test_config_schema_accepts_markdown_template_paths_or_null() -> None:
    public_schema = schema()

    for memory_key, legacy_key in (
        ("agents_template", "amd_agents_template"),
        ("agents_minimal_template", "amd_agents_minimal_template"),
        ("sase_template", "memory_sase_template"),
        ("readme_template", "memory_readme_template"),
    ):
        for value in (None, "templates/AGENTS.md"):
            for config in (
                {"memory": {memory_key: value}},
                # Legacy top-level form keeps validating.
                {legacy_key: value},
            ):
                errors = sorted(
                    Draft7Validator(public_schema).iter_errors(config),
                    key=lambda error: list(error.absolute_path),
                )

                assert errors == [], "\n".join(
                    format_schema_error(error) for error in errors
                )

        assert public_schema["properties"][legacy_key]["deprecated"] is True


def test_config_schema_accepts_boolean_sase_management_marker() -> None:
    public_schema = schema()

    for is_managed in (False, True):
        errors = tuple(
            Draft7Validator(public_schema).iter_errors({"is_sase_managed": is_managed})
        )
        assert errors == ()

    with pytest.raises(ValidationError):
        Draft7Validator(public_schema).validate({"is_sase_managed": "true"})


def test_config_schema_rejects_retired_memory_opt_in() -> None:
    with pytest.raises(ValidationError):
        Draft7Validator(schema()).validate({"memory": {"enabled": True}})


def test_config_schema_accepts_closed_commit_hooks_object() -> None:
    validator = Draft7Validator(schema())

    assert (
        tuple(
            validator.iter_errors(
                {"commit_hooks": {"before": "just fix", "after": "just deploy"}}
            )
        )
        == ()
    )

    with pytest.raises(ValidationError):
        validator.validate({"commit_hooks": {"during": "just nope"}})


def test_config_schema_accepts_ace_tool_call_slow_threshold() -> None:
    public_schema = schema()
    config = {"ace": {"tool_calls": {"slow_threshold_seconds": 30}}}

    errors = sorted(
        Draft7Validator(public_schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert errors == [], "\n".join(format_schema_error(error) for error in errors)


def test_config_schema_rejects_negative_ace_tool_call_slow_threshold() -> None:
    public_schema = schema()
    config = {"ace": {"tool_calls": {"slow_threshold_seconds": -1}}}

    errors = sorted(
        Draft7Validator(public_schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert any(
        list(error.absolute_path) == ["ace", "tool_calls", "slow_threshold_seconds"]
        and "less than the minimum" in error.message
        for error in errors
    )


@pytest.mark.parametrize("minutes", [30, 0.25])
def test_config_schema_accepts_positive_ace_update_check_interval(
    minutes: float,
) -> None:
    Draft7Validator(schema()).validate(
        {"ace": {"updates": {"check_interval_minutes": minutes}}}
    )


@pytest.mark.parametrize("minutes", [0, -1])
def test_config_schema_rejects_nonpositive_ace_update_check_interval(
    minutes: float,
) -> None:
    with pytest.raises(ValidationError):
        Draft7Validator(schema()).validate(
            {"ace": {"updates": {"check_interval_minutes": minutes}}}
        )


@pytest.mark.parametrize("minutes", [60, 0.25])
def test_config_schema_accepts_positive_ace_update_recompute_interval(
    minutes: float,
) -> None:
    Draft7Validator(schema()).validate(
        {"ace": {"updates": {"recompute_interval_minutes": minutes}}}
    )


@pytest.mark.parametrize("minutes", [0, -1])
def test_config_schema_rejects_nonpositive_ace_update_recompute_interval(
    minutes: float,
) -> None:
    with pytest.raises(ValidationError):
        Draft7Validator(schema()).validate(
            {"ace": {"updates": {"recompute_interval_minutes": minutes}}}
        )
