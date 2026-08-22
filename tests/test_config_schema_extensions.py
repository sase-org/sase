"""Schema coverage for artifact-ref roots, file hooks, and required plugins."""

from __future__ import annotations

from typing import Any

import pytest
from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError

from tests._config_schema_helpers import schema


pytestmark = pytest.mark.contract


def test_config_schema_validates_artifact_refs_file_roots() -> None:
    validator = Draft7Validator(schema())
    validator.validate(
        {
            "artifact_refs": {
                "file": {
                    "roots": [
                        {
                            "name": "project-notes",
                            "path": "~/notes",
                            "path_globs": ["**/*.md", "!private/**"],
                        },
                        {"name": "tmp", "path": "/tmp"},
                    ]
                }
            }
        }
    )

    for invalid in (
        {"artifactRefs": {"file": {"roots": []}}},
        {"artifact_refs": {"files": {"roots": []}}},
        {"artifact_refs": {"file": {"root": []}}},
        {"artifact_refs": {"file": {"roots": [{"name": "Bad", "path": "/tmp"}]}}},
        {"artifact_refs": {"file": {"roots": [{"name": "ok", "path": ""}]}}},
        {
            "artifact_refs": {
                "file": {
                    "roots": [{"name": "ok", "path": "/tmp", "path_globs": "*.md"}]
                }
            }
        },
        {
            "artifact_refs": {
                "file": {"roots": [{"name": "ok", "path": "/tmp", "extra": True}]}
            }
        },
    ):
        with pytest.raises(ValidationError):
            validator.validate(invalid)


def test_config_schema_accepts_file_hooks() -> None:
    Draft7Validator(schema()).validate(
        {
            "file_hooks": [
                {
                    "name": "research-highlights",
                    "description": "Render new research reports.",
                    "command": "bob highlights create",
                    "filters": {
                        "projects": ["sase"],
                        "sidecars": ["research"],
                        "path_globs": ["20*/**/*.md", "!20*/*/*__*.md"],
                        "agent_name_globs": [
                            "!research.*.cld",
                            "!research.*.cdx",
                        ],
                        "ops": ["ADD"],
                        "producers": ["commit", "sdd", "finalizer"],
                    },
                    "timeout": "120s",
                },
                {
                    "name": "quick_check",
                    "command": "check-file",
                    "timeout": "250ms",
                },
                {
                    "name": "empty_filters",
                    "command": "check-file",
                    "filters": {},
                },
                {
                    "use": "sase-research-artifacts@research-highlights",
                    "command": "bob highlights create",
                    "filters": {"path_globs": ["reports/**/*.md"]},
                },
            ]
        }
    )


@pytest.mark.parametrize(
    "hook",
    [
        {},
        {"name": "valid"},
        {"command": "run"},
        {"name": "Not A Slug", "command": "run"},
        {"name": "valid", "command": ""},
        {"name": "valid", "command": "run", "projects": ["sase"]},
        {"name": "valid", "command": "run", "sidecars": ["research"]},
        {"name": "valid", "command": "run", "path_globs": ["*.md"]},
        {"name": "valid", "command": "run", "agent_name_globs": ["research.*"]},
        {"name": "valid", "command": "run", "ops": ["ADD"]},
        {"name": "valid", "command": "run", "filters": None},
        {"name": "valid", "command": "run", "filters": []},
        {"name": "valid", "command": "run", "filters": {"unknown": True}},
        {"name": "valid", "command": "run", "filters": {"path_globs": "*.md"}},
        {"name": "valid", "command": "run", "filters": {"ops": ["CREATE"]}},
        {"name": "valid", "command": "run", "filters": {"producers": ["copy"]}},
        {"name": "valid", "command": "run", "producers": ["commit"]},
        {"name": "valid", "command": "run", "timeout": "2 days"},
        {"name": "valid", "command": "run", "unknown": True},
        {"name": "valid", "command": "run", "globs": ["*.md"]},
        {"use": "research-highlights", "command": "run"},
    ],
)
def test_config_schema_rejects_invalid_file_hooks(hook: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Draft7Validator(schema()).validate({"file_hooks": [hook]})


def test_config_schema_accepts_plugins_required() -> None:
    Draft7Validator(schema()).validate(
        {
            "plugins": {
                "required": [
                    "sase-github",
                    "sase-research-artifacts>=0.2",
                ]
            }
        }
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"plugins": {"required": "sase-github"}},
        {"plugins": {"required": [""]}},
        {"plugins": {"required": [1]}},
        {"plugins": {"unknown": True}},
        {"plugins": {"required": [], "extra": True}},
    ],
)
def test_config_schema_rejects_invalid_plugins_required(
    payload: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        Draft7Validator(schema()).validate(payload)
