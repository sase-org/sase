"""Regression coverage for the user-facing SASE config schema."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_default_config_matches_public_schema() -> None:
    schema = json.loads((REPO_ROOT / "config/sase.schema.json").read_text())
    default_config = yaml.safe_load(
        (REPO_ROOT / "src/sase/default_config.yml").read_text()
    )

    Draft7Validator.check_schema(schema)
    errors = sorted(
        Draft7Validator(schema).iter_errors(default_config),
        key=lambda error: list(error.absolute_path),
    )

    assert errors == [], "\n".join(_format_schema_error(error) for error in errors)


def test_config_schema_accepts_xprompt_input_descriptions() -> None:
    schema = json.loads((REPO_ROOT / "config/sase.schema.json").read_text())
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
        Draft7Validator(schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert errors == [], "\n".join(_format_schema_error(error) for error in errors)


def test_config_schema_accepts_xprompt_log_skill_use() -> None:
    schema = json.loads((REPO_ROOT / "config/sase.schema.json").read_text())
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
        Draft7Validator(schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert errors == [], "\n".join(_format_schema_error(error) for error in errors)


def test_config_schema_accepts_amd_h1_title_string_or_null() -> None:
    schema = json.loads((REPO_ROOT / "config/sase.schema.json").read_text())

    for config in ({"amd_h1_title": None}, {"amd_h1_title": "Agent Instructions"}):
        errors = sorted(
            Draft7Validator(schema).iter_errors(config),
            key=lambda error: list(error.absolute_path),
        )

        assert errors == [], "\n".join(_format_schema_error(error) for error in errors)


def test_config_schema_accepts_worker_models_mapping() -> None:
    schema = json.loads((REPO_ROOT / "config/sase.schema.json").read_text())
    config = {
        "llm_provider": {
            "worker_models": {
                "claude": "codex/gpt-5.5",
                "codex/o3": "claude/opus",
            }
        }
    }

    errors = sorted(
        Draft7Validator(schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert errors == [], "\n".join(_format_schema_error(error) for error in errors)


def test_config_schema_rejects_legacy_worker_model_field() -> None:
    schema = json.loads((REPO_ROOT / "config/sase.schema.json").read_text())
    config = {"llm_provider": {"worker_model": "codex/gpt-5.5"}}

    errors = sorted(
        Draft7Validator(schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert any(
        list(error.absolute_path) == ["llm_provider"]
        and "Additional properties are not allowed" in error.message
        and "worker_model" in error.message
        for error in errors
    )


def test_config_schema_requires_sibling_repo_descriptions() -> None:
    schema = json.loads((REPO_ROOT / "config/sase.schema.json").read_text())
    config = {
        "sibling_repos": [
            {
                "name": "core",
                "path": "../sase-core",
            }
        ]
    }

    errors = sorted(
        Draft7Validator(schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert any(
        list(error.absolute_path) == ["sibling_repos", 0]
        and "'description' is a required property" in error.message
        for error in errors
    )


def _format_schema_error(error: ValidationError) -> str:
    path = ".".join(str(part) for part in error.absolute_path) or "<root>"
    return f"{path}: {error.message}"
