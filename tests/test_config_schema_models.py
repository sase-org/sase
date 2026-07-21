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


def test_config_schema_rejects_obsolete_default_model_field() -> None:
    """A stale ``llm_provider.default_model`` is rejected (use model_aliases.default)."""
    public_schema = schema()
    config = {"llm_provider": {"default_model": "claude/opus"}}

    errors = sorted(
        Draft7Validator(public_schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert any(
        list(error.absolute_path) == ["llm_provider"]
        and "Additional properties are not allowed" in error.message
        and "default_model" in error.message
        for error in errors
    )


def test_config_schema_accepts_builtin_model_aliases_with_at_references() -> None:
    """``model_aliases.builtin`` stays a string map for ``@alias`` references."""
    public_schema = schema()
    config = {
        "llm_provider": {
            "model_aliases": {
                "builtin": {
                    "default": "claude/opus",
                    "coder": "@default",
                    "codex_coder": "claude/opus",
                    "cheaper": "claude/opus@medium | codex/gpt-5.5",
                    "cheapest": "claude/sonnet | codex/gpt-5.3-codex-spark",
                    "small_phase_worker": "@cheaper",
                    "medium_phase_worker": "@default",
                    "large_phase_worker": "@smartest",
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
                    "coders": {"description": "Coder follow-up aliases."},
                    "phase_worker": {"description": "Phase worker aliases."},
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


def test_config_schema_accepts_custom_alias_coalesced_into_coders_bucket() -> None:
    public_schema = schema()
    config = {
        "llm_provider": {
            "model_aliases": {
                "custom": {
                    "review_coder": {
                        "model": "codex/gpt-5.6-sol",
                        "description": "Reviews coder follow-ups.",
                        "bucket": "coders",
                    }
                },
                "buckets": {"coders": {"description": "All coder roles."}},
            }
        }
    }

    errors = sorted(
        Draft7Validator(public_schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert errors == [], "\n".join(format_schema_error(error) for error in errors)


def test_config_schema_accepts_custom_alias_coalesced_into_phase_worker_bucket() -> (
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
                        "bucket": "phase_worker",
                    }
                },
                "buckets": {"phase_worker": {"description": "All phase-worker roles."}},
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
    config = {"llm_provider": {"model_aliases": {"coder": "@default"}}}

    errors = sorted(
        Draft7Validator(public_schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert any(
        list(error.absolute_path) == ["llm_provider", "model_aliases"]
        and "Additional properties are not allowed" in error.message
        and "coder" in error.message
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
