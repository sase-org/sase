"""Config schema coverage for model alias configuration."""

from __future__ import annotations

from typing import Any

import pytest
from jsonschema import Draft7Validator

from tests._config_schema_helpers import format_schema_error, schema


def test_config_schema_rejects_worker_models_mapping() -> None:
    """``worker_models`` was removed by the model-alias migration (epic sase-5d)."""
    public_schema = schema()
    config = {
        "llm_provider": {
            "worker_models": {
                "claude": "codex/gpt-5.6-sol",
                "codex/o3": "claude/opus",
            }
        }
    }

    errors = sorted(
        Draft7Validator(public_schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert any(
        list(error.absolute_path) == ["llm_provider"]
        and "Additional properties are not allowed" in error.message
        and "worker_models" in error.message
        for error in errors
    )


def test_config_schema_accepts_scalar_launch_model_fields() -> None:
    """Scalar launch defaults use the same string grammar as ``%model``."""
    public_schema = schema()
    config = {
        "llm_provider": {
            "default_model": "@large",
            "epic_lander_model": "claude/opus",
            "big_epic_lander_model": "claude/opus@max || codex/gpt-5.6-sol@max",
        }
    }

    errors = sorted(
        Draft7Validator(public_schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert errors == [], "\n".join(format_schema_error(error) for error in errors)


def test_config_schema_accepts_builtin_model_aliases_with_at_references() -> None:
    """``model_aliases.builtin`` stays a string map for ``@alias`` references."""
    public_schema = schema()
    config = {
        "llm_provider": {
            "model_aliases": {
                "builtin": {
                    "xsmall": "claude/sonnet@medium | codex/gpt-5.5@medium",
                    "small": "@xsmall@high",
                    "medium": "claude/sonnet@xhigh | codex/gpt-5.5@xhigh",
                    "large": "claude/opus@xhigh | codex/gpt-5.6-sol@xhigh",
                    "xlarge": "claude/opus@max || codex/gpt-5.6-sol@max",
                }
            }
        }
    }

    errors = sorted(
        Draft7Validator(public_schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert errors == [], "\n".join(format_schema_error(error) for error in errors)


def test_config_schema_accepts_described_custom_model_aliases() -> None:
    public_schema = schema()
    config = {
        "llm_provider": {
            "model_aliases": {
                "custom": {
                    "blogger": {
                        "model": "claude/opus",
                        "description": "Agents that draft and edit blog posts.",
                    }
                }
            }
        }
    }

    errors = sorted(
        Draft7Validator(public_schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert errors == [], "\n".join(format_schema_error(error) for error in errors)


def test_config_schema_accepts_model_alias_buckets() -> None:
    public_schema = schema()
    config = {
        "llm_provider": {
            "model_aliases": {
                "custom": {
                    "research_a": {
                        "model": "codex/gpt-5.6-sol",
                        "description": "Lead researcher.",
                        "bucket": "research",
                    }
                },
                "buckets": {
                    "worker": {"description": "Phase worker aliases."},
                    "research": {"description": "Research-swarm model roles."},
                },
            }
        }
    }

    errors = sorted(
        Draft7Validator(public_schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert errors == [], "\n".join(format_schema_error(error) for error in errors)


def test_config_schema_accepts_custom_alias_coalesced_into_user_bucket() -> None:
    public_schema = schema()
    config = {
        "llm_provider": {
            "model_aliases": {
                "custom": {
                    "reviewer": {
                        "model": "codex/gpt-5.6-sol",
                        "description": "Reviews implementation follow-ups.",
                        "bucket": "coding",
                    }
                },
                "buckets": {"coding": {"description": "Implementation roles."}},
            }
        }
    }

    errors = sorted(
        Draft7Validator(public_schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert errors == [], "\n".join(format_schema_error(error) for error in errors)


def test_config_schema_accepts_custom_alias_coalesced_into_custom_worker_bucket() -> (
    None
):
    public_schema = schema()
    config = {
        "llm_provider": {
            "model_aliases": {
                "custom": {
                    "phase_reviewer": {
                        "model": "codex/gpt-5.6-sol",
                        "description": "Reviews completed phases.",
                        "bucket": "worker",
                    }
                },
                "buckets": {"worker": {"description": "All phase-worker roles."}},
            }
        }
    }

    errors = sorted(
        Draft7Validator(public_schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert errors == [], "\n".join(format_schema_error(error) for error in errors)


def test_config_schema_rejects_unknown_model_alias_bucket_metadata_key() -> None:
    public_schema = schema()
    config = {
        "llm_provider": {
            "model_aliases": {
                "buckets": {"research": {"description": "Research.", "extra": True}}
            }
        }
    }

    errors = list(Draft7Validator(public_schema).iter_errors(config))

    assert any(
        "Additional properties are not allowed" in error.message for error in errors
    )


@pytest.mark.parametrize(
    ("alias_value", "message"),
    [
        ({"model": "claude/opus"}, "'description' is a required property"),
        ({"description": "Draft posts."}, "'model' is a required property"),
        (
            {"model": "", "description": "Draft posts."},
            "'' should be non-empty",
        ),
        (
            {"model": "claude/opus", "description": ""},
            "'' should be non-empty",
        ),
        (
            {"model": "claude/opus", "description": "x" * 161},
            "is too long",
        ),
        (
            {
                "model": "claude/opus",
                "description": "Draft posts.",
                "extra": True,
            },
            "Additional properties are not allowed",
        ),
    ],
)
def test_config_schema_rejects_bad_custom_model_aliases(
    alias_value: dict[str, Any],
    message: str,
) -> None:
    public_schema = schema()
    config = {
        "llm_provider": {
            "model_aliases": {"custom": {"blogger": alias_value}},
        }
    }

    errors = sorted(
        Draft7Validator(public_schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert any(message in error.message for error in errors)


def test_config_schema_rejects_flat_model_alias_entry() -> None:
    public_schema = schema()
    config = {"llm_provider": {"model_aliases": {"blogger": "@default"}}}

    errors = sorted(
        Draft7Validator(public_schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert any(
        list(error.absolute_path) == ["llm_provider", "model_aliases"]
        and "Additional properties are not allowed" in error.message
        and "blogger" in error.message
        for error in errors
    )


def test_config_schema_rejects_top_level_custom_model_aliases() -> None:
    public_schema = schema()
    config = {
        "llm_provider": {
            "custom_model_aliases": {
                "blogger": {
                    "model": "claude/opus",
                    "description": "Draft posts.",
                }
            }
        }
    }

    errors = sorted(
        Draft7Validator(public_schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert any(
        list(error.absolute_path) == ["llm_provider"]
        and "Additional properties are not allowed" in error.message
        and "custom_model_aliases" in error.message
        for error in errors
    )


def test_config_schema_rejects_legacy_worker_model_field() -> None:
    public_schema = schema()
    config = {"llm_provider": {"worker_model": "codex/gpt-5.6-sol"}}

    errors = sorted(
        Draft7Validator(public_schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert any(
        list(error.absolute_path) == ["llm_provider"]
        and "Additional properties are not allowed" in error.message
        and "worker_model" in error.message
        for error in errors
    )
