"""Regression coverage for the user-facing SASE config schema."""

from __future__ import annotations

import importlib.resources
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError

from sase.config.inventory import config_schema_path, load_config_schema


REPO_ROOT = Path(__file__).resolve().parents[1]


def _schema() -> dict[str, Any]:
    return load_config_schema()


def test_config_schema_resolves_inside_sase_package() -> None:
    schema_path = config_schema_path().resolve()
    package_root = Path(str(importlib.resources.files("sase"))).resolve()

    assert schema_path.is_file()
    assert schema_path.is_relative_to(package_root)
    json.loads(schema_path.read_text(encoding="utf-8"))


def test_default_config_matches_public_schema() -> None:
    schema = _schema()
    default_config = yaml.safe_load(
        (REPO_ROOT / "src/sase/default_config.yml").read_text()
    )

    Draft7Validator.check_schema(schema)
    errors = sorted(
        Draft7Validator(schema).iter_errors(default_config),
        key=lambda error: list(error.absolute_path),
    )

    assert errors == [], "\n".join(_format_schema_error(error) for error in errors)


def test_config_schema_accepts_max_running_agents() -> None:
    Draft7Validator(_schema()).validate({"max_running_agents": 1})
    Draft7Validator(_schema()).validate({"max_running_agents": 25})


def test_config_schema_rejects_max_running_agents_below_minimum() -> None:
    with pytest.raises(ValidationError):
        Draft7Validator(_schema()).validate({"max_running_agents": 0})


def test_get_max_running_agents_reads_merged_config(monkeypatch) -> None:
    from sase.config import core as config_core

    monkeypatch.setattr(
        config_core,
        "load_merged_config",
        lambda: {"max_running_agents": 7},
    )

    assert config_core.get_max_running_agents() == 7


def test_config_schema_accepts_xprompt_input_descriptions() -> None:
    schema = _schema()
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
    schema = _schema()
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


def test_config_schema_rejects_retired_memory_keywords() -> None:
    with pytest.raises(ValidationError):
        Draft7Validator(_schema()).validate(
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
    schema = _schema()

    for config in ({"amd_h1_title": None}, {"amd_h1_title": "Agent Instructions"}):
        errors = sorted(
            Draft7Validator(schema).iter_errors(config),
            key=lambda error: list(error.absolute_path),
        )

        assert errors == [], "\n".join(_format_schema_error(error) for error in errors)


def test_config_schema_accepts_markdown_template_paths_or_null() -> None:
    schema = _schema()

    for key in (
        "amd_agents_template",
        "amd_agents_minimal_template",
        "memory_sase_template",
        "memory_readme_template",
    ):
        for value in (None, "templates/AGENTS.md"):
            errors = sorted(
                Draft7Validator(schema).iter_errors({key: value}),
                key=lambda error: list(error.absolute_path),
            )

            assert errors == [], "\n".join(
                _format_schema_error(error) for error in errors
            )


def test_config_schema_accepts_boolean_sase_management_marker() -> None:
    schema = _schema()

    for is_managed in (False, True):
        errors = tuple(
            Draft7Validator(schema).iter_errors({"is_sase_managed": is_managed})
        )
        assert errors == ()

    with pytest.raises(ValidationError):
        Draft7Validator(schema).validate({"is_sase_managed": "true"})


def test_config_schema_rejects_retired_memory_opt_in() -> None:
    with pytest.raises(ValidationError):
        Draft7Validator(_schema()).validate({"memory": {"enabled": True}})


def test_config_schema_accepts_closed_commit_hooks_object() -> None:
    schema = _schema()
    validator = Draft7Validator(schema)

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


def test_config_schema_accepts_agent_family_plan_approval_defaults() -> None:
    schema = _schema()
    config = {
        "agent_family": {
            "plan_approval": {
                "default_members": {
                    "improve_plan": True,
                    "tester": False,
                }
            }
        }
    }

    errors = sorted(
        Draft7Validator(schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert errors == [], "\n".join(_format_schema_error(error) for error in errors)


def test_config_schema_accepts_ace_tool_call_slow_threshold() -> None:
    schema = _schema()
    config = {"ace": {"tool_calls": {"slow_threshold_seconds": 30}}}

    errors = sorted(
        Draft7Validator(schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert errors == [], "\n".join(_format_schema_error(error) for error in errors)


def test_config_schema_rejects_negative_ace_tool_call_slow_threshold() -> None:
    schema = _schema()
    config = {"ace": {"tool_calls": {"slow_threshold_seconds": -1}}}

    errors = sorted(
        Draft7Validator(schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert any(
        list(error.absolute_path) == ["ace", "tool_calls", "slow_threshold_seconds"]
        and "less than the minimum" in error.message
        for error in errors
    )


def test_config_schema_rejects_worker_models_mapping() -> None:
    """``worker_models`` was removed by the model-alias migration (epic sase-5d)."""
    schema = _schema()
    config = {
        "llm_provider": {
            "worker_models": {
                "claude": "codex/gpt-5.6-sol",
                "codex/o3": "claude/opus",
            }
        }
    }

    errors = sorted(
        Draft7Validator(schema).iter_errors(config),
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
    schema = _schema()
    config = {"llm_provider": {"default_model": "claude/opus"}}

    errors = sorted(
        Draft7Validator(schema).iter_errors(config),
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
    schema = _schema()
    config = {
        "llm_provider": {
            "model_aliases": {
                "builtin": {
                    "default": "claude/opus",
                    "coder": "@default",
                    "codex_coder": "claude/opus",
                }
            }
        }
    }

    errors = sorted(
        Draft7Validator(schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert errors == [], "\n".join(_format_schema_error(error) for error in errors)


def test_config_schema_accepts_described_custom_model_aliases() -> None:
    schema = _schema()
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
        Draft7Validator(schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert errors == [], "\n".join(_format_schema_error(error) for error in errors)


def test_config_schema_accepts_model_alias_buckets() -> None:
    schema = _schema()
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
                    "research": {"description": "Research-swarm model roles."},
                },
            }
        }
    }

    errors = sorted(
        Draft7Validator(schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert errors == [], "\n".join(_format_schema_error(error) for error in errors)


def test_config_schema_accepts_custom_alias_coalesced_into_coders_bucket() -> None:
    schema = _schema()
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
        Draft7Validator(schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert errors == [], "\n".join(_format_schema_error(error) for error in errors)


def test_config_schema_rejects_unknown_model_alias_bucket_metadata_key() -> None:
    schema = _schema()
    config = {
        "llm_provider": {
            "model_aliases": {
                "buckets": {"research": {"description": "Research.", "extra": True}}
            }
        }
    }

    errors = list(Draft7Validator(schema).iter_errors(config))

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
    schema = _schema()
    config = {
        "llm_provider": {
            "model_aliases": {"custom": {"blogger": alias_value}},
        }
    }

    errors = sorted(
        Draft7Validator(schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert any(message in error.message for error in errors)


def test_config_schema_rejects_flat_model_alias_entry() -> None:
    schema = _schema()
    config = {"llm_provider": {"model_aliases": {"coder": "@default"}}}

    errors = sorted(
        Draft7Validator(schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert any(
        list(error.absolute_path) == ["llm_provider", "model_aliases"]
        and "Additional properties are not allowed" in error.message
        and "coder" in error.message
        for error in errors
    )


def test_config_schema_rejects_top_level_custom_model_aliases() -> None:
    schema = _schema()
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
        Draft7Validator(schema).iter_errors(config),
        key=lambda error: list(error.absolute_path),
    )

    assert any(
        list(error.absolute_path) == ["llm_provider"]
        and "Additional properties are not allowed" in error.message
        and "custom_model_aliases" in error.message
        for error in errors
    )


def test_config_schema_rejects_legacy_worker_model_field() -> None:
    schema = _schema()
    config = {"llm_provider": {"worker_model": "codex/gpt-5.6-sol"}}

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


@pytest.mark.parametrize("repos_key", ["linked_repos", "sibling_repos"])
def test_config_schema_requires_linked_repo_descriptions(repos_key: str) -> None:
    # Both the canonical ``linked_repos`` key and the deprecated ``sibling_repos``
    # alias share the same item schema, so each enforces the required fields.
    schema = _schema()
    config = {
        repos_key: [
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
        list(error.absolute_path) == [repos_key, 0]
        and "'description' is a required property" in error.message
        for error in errors
    )


def test_config_schema_accepts_linked_repo_auto_clone_and_default_opt_out() -> None:
    schema = _schema()
    config = {
        "default_linked_repos": False,
        "linked_repos": [
            {
                "name": "core",
                "path": "../sase-core",
                "description": "Shared core.",
                "auto_clone": True,
            }
        ],
    }

    assert list(Draft7Validator(schema).iter_errors(config)) == []


def test_config_schema_accepts_canonical_linked_and_sidecar_repos() -> None:
    schema = _schema()
    config = {
        "repos": {
            "linked": [
                {
                    "name": "core",
                    "path": "../sase-core",
                    "description": "Shared core.",
                    "auto_clone": True,
                }
            ],
            "sidecar": [
                {
                    "name": "research",
                    "repo": "sase-org/sase--research",
                    "description": "Durable research.",
                    "auto_clone": False,
                    "visibility": "private",
                    "disabled": False,
                }
            ],
        }
    }

    assert list(Draft7Validator(schema).iter_errors(config)) == []


@pytest.mark.parametrize(
    ("entry", "field"),
    [
        ({"name": "research", "visibility": "internal"}, "visibility"),
        ({"name": "research", "disabled": "no"}, "disabled"),
        ({"name": "research", "auto_clone": "yes"}, "auto_clone"),
    ],
)
def test_config_schema_rejects_invalid_sidecar_controls(
    entry: dict[str, object], field: str
) -> None:
    config = {"repos": {"sidecar": [entry]}}

    errors = list(Draft7Validator(_schema()).iter_errors(config))

    assert [list(error.absolute_path) for error in errors] == [
        ["repos", "sidecar", 0, field]
    ]


@pytest.mark.parametrize(
    ("config", "expected_path"),
    [
        ({"default_linked_repos": "no"}, ["default_linked_repos"]),
        (
            {
                "linked_repos": [
                    {
                        "name": "core",
                        "path": "../sase-core",
                        "description": "Shared core.",
                        "auto_clone": "yes",
                    }
                ]
            },
            ["linked_repos", 0, "auto_clone"],
        ),
    ],
)
def test_config_schema_rejects_non_boolean_linked_repo_controls(
    config: dict[str, object], expected_path: list[object]
) -> None:
    errors = list(Draft7Validator(_schema()).iter_errors(config))

    assert [list(error.absolute_path) for error in errors] == [expected_path]


def _format_schema_error(error: ValidationError) -> str:
    path = ".".join(str(part) for part in error.absolute_path) or "<root>"
    return f"{path}: {error.message}"
