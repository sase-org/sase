"""Config schema coverage for linked and sidecar repositories."""

from __future__ import annotations

import pytest
from jsonschema import Draft7Validator

from tests._config_schema_helpers import schema, with_machine_name


@pytest.mark.parametrize("repos_key", ["linked_repos", "sibling_repos"])
def test_config_schema_requires_linked_repo_descriptions(repos_key: str) -> None:
    # Both the canonical ``linked_repos`` key and the deprecated ``sibling_repos``
    # alias share the same item schema, so each enforces the required fields.
    public_schema = schema()
    config = {
        repos_key: [
            {
                "name": "core",
                "path": "../sase-core",
            }
        ]
    }

    errors = sorted(
        Draft7Validator(public_schema).iter_errors(with_machine_name(config)),
        key=lambda error: list(error.absolute_path),
    )

    assert any(
        list(error.absolute_path) == [repos_key, 0]
        and "'description' is a required property" in error.message
        for error in errors
    )


def test_config_schema_accepts_linked_repo_auto_clone_and_default_opt_out() -> None:
    public_schema = schema()
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

    assert (
        list(Draft7Validator(public_schema).iter_errors(with_machine_name(config)))
        == []
    )


def test_config_schema_accepts_canonical_linked_and_sidecar_repos() -> None:
    public_schema = schema()
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

    assert (
        list(Draft7Validator(public_schema).iter_errors(with_machine_name(config)))
        == []
    )


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

    errors = list(Draft7Validator(schema()).iter_errors(with_machine_name(config)))

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
    errors = list(Draft7Validator(schema()).iter_errors(with_machine_name(config)))

    assert [list(error.absolute_path) for error in errors] == [expected_path]
