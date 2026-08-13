"""Config schema coverage for linked and sidecar repositories."""

from __future__ import annotations

from typing import Any

import pytest
from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError

from tests._config_schema_helpers import schema


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
        Draft7Validator(public_schema).iter_errors(config),
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

    assert list(Draft7Validator(public_schema).iter_errors(config)) == []


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
            "sidecar": {
                "custom": {
                    "research": {
                        "repo": "sase-org/sase--research",
                        "description": "Durable research.",
                        "auto_clone": False,
                        "visibility": "private",
                        "disabled": False,
                        "ref": {
                            "kind": "research",
                            "icon": "∴",
                            "inventory": {"globs": ["**/*.md"]},
                            "publication": {
                                "link": "vcs_permalink",
                                "referenced_by": "markdown_table",
                            },
                        },
                    }
                }
            },
        }
    }

    assert list(Draft7Validator(public_schema).iter_errors(config)) == []


def test_config_schema_documents_intrinsic_agents_sidecar_contract() -> None:
    public_schema = schema()
    sidecar = public_schema["definitions"]["sidecarRepo"]["properties"]

    assert "beads" in public_schema["properties"]["default_linked_repos"]["description"]
    assert (
        "hidden agents"
        in public_schema["properties"]["default_linked_repos"]["description"]
    )
    assert (
        "beads"
        in public_schema["properties"]["repos"]["properties"]["sidecar"]["description"]
    )
    assert (
        "hidden agents"
        in public_schema["properties"]["repos"]["properties"]["sidecar"]["description"]
    )
    assert (
        "~/.sase/projects/<project_key>/repos/agents"
        in public_schema["properties"]["repos"]["properties"]["sidecar"]["description"]
    )
    assert "never exposed" in sidecar["auto_clone"]["description"]
    assert "agents sidecar" in sidecar["disabled"]["description"]
    assert "private" in sidecar["visibility"]["description"]
    assert sidecar["ref"]["$ref"] == "#/definitions/sidecarRef"


@pytest.mark.parametrize(
    ("entry", "field"),
    [
        ({"visibility": "internal"}, "visibility"),
        ({"disabled": "no"}, "disabled"),
        ({"auto_clone": "yes"}, "auto_clone"),
    ],
)
def test_config_schema_rejects_invalid_sidecar_controls(
    entry: dict[str, object], field: str
) -> None:
    config = {"repos": {"sidecar": {"custom": {"research": entry}}}}

    errors = list(Draft7Validator(schema()).iter_errors(config))

    assert [list(error.absolute_path) for error in errors] == [
        ["repos", "sidecar", "custom", "research", field]
    ]


@pytest.mark.parametrize(
    ("entry", "expected_path"),
    [
        ({"ref": "no"}, ["repos", "sidecar", "custom", "research", "ref"]),
        (
            {"ref": {"use": ""}},
            ["repos", "sidecar", "custom", "research", "ref", "use"],
        ),
        (
            {"ref": {"filters": "no"}},
            ["repos", "sidecar", "custom", "research", "ref", "filters"],
        ),
        (
            {"ref": {"filters": {"path_globs": [""]}}},
            [
                "repos",
                "sidecar",
                "custom",
                "research",
                "ref",
                "filters",
                "path_globs",
                0,
            ],
        ),
    ],
)
def test_config_schema_rejects_invalid_sidecar_ref_controls(
    entry: dict[str, object], expected_path: list[object]
) -> None:
    config = {"repos": {"sidecar": {"custom": {"research": entry}}}}

    errors = list(Draft7Validator(schema()).iter_errors(config))

    assert [list(error.absolute_path) for error in errors] == [expected_path]


def test_config_schema_rejects_retired_sidecar_ref_xprompt() -> None:
    config = {
        "repos": {
            "sidecar": {
                "custom": {
                    "research": {
                        "ref": {"xprompt": "Research {{ file_path }}"},
                    }
                }
            }
        }
    }

    errors = list(Draft7Validator(schema()).iter_errors(config))

    assert [list(error.absolute_path) for error in errors] == [
        ["repos", "sidecar", "custom", "research", "ref"]
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
    errors = list(Draft7Validator(schema()).iter_errors(config))

    assert [list(error.absolute_path) for error in errors] == [expected_path]


def test_config_schema_accepts_bucketed_sidecar_repos() -> None:
    """The canonical two-bucket ``repos.sidecar`` mapping validates."""
    Draft7Validator(schema()).validate(
        {
            "repos": {
                "sidecar": {
                    "builtin": {
                        "plans": {"auto_clone": True},
                        "beads": {"auto_clone": True},
                        "agents": {"visibility": "private"},
                    },
                    "custom": {
                        "research": {"description": "Durable research."},
                        "notes": {"disabled": True},
                    },
                }
            }
        }
    )


def test_config_schema_rejects_legacy_sidecar_list() -> None:
    """The removed list form no longer validates."""
    with pytest.raises(ValidationError):
        Draft7Validator(schema()).validate(
            {"repos": {"sidecar": [{"name": "research", "description": "Docs."}]}}
        )


@pytest.mark.parametrize(
    "sidecar",
    [
        pytest.param({"custom": {"plans": {}}}, id="reserved-role-in-custom"),
        pytest.param({"builtin": {"research": {}}}, id="document-role-in-builtin"),
        pytest.param(
            {"custom": {"research": {"name": "research"}}}, id="leftover-name-field"
        ),
        pytest.param({"other": {"research": {}}}, id="unknown-bucket"),
    ],
)
def test_config_schema_rejects_mis_bucketed_sidecar_repos(
    sidecar: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        Draft7Validator(schema()).validate({"repos": {"sidecar": sidecar}})
