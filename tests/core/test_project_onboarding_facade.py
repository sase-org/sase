"""Adapter contract tests for the published project-onboarding core surface."""

from __future__ import annotations

from sase.core.project_onboarding_facade import (
    PROJECT_ONBOARDING_WIRE_SCHEMA_VERSION,
    classify_project_candidates,
    evaluate_repo_creation_form,
)
from sase.core.rust import require_rust_binding


def test_schema_version_matches_binding() -> None:
    assert PROJECT_ONBOARDING_WIRE_SCHEMA_VERSION == 1
    binding = require_rust_binding("project_onboarding_wire_schema_version")
    assert int(binding()) == PROJECT_ONBOARDING_WIRE_SCHEMA_VERSION


def test_classify_hides_sidecar_suffix_and_keeps_user_double_dash() -> None:
    result = classify_project_candidates(
        {
            "schema_version": 1,
            "workflow_type": "gh",
            "sidecar_roles": ["plans", "beads", "research", "sdd"],
            "owned_namespaces": ["sase-org"],
            "remote": [
                {
                    "identity_key": "github.com/sase-org/sase--plans",
                    "ref": "sase-org/sase--plans",
                    "display": "sase-org/sase--plans",
                    "name": "sase--plans",
                },
                {
                    "identity_key": "github.com/sase-org/foo--bar",
                    "ref": "sase-org/foo--bar",
                    "display": "sase-org/foo--bar",
                    "name": "foo--bar",
                },
            ],
        }
    )
    assert result["schema_version"] == 1
    hidden = {row["display"]: row["hidden_reason"] for row in result["search_only"]}
    assert hidden["sase-org/sase--plans"] == "sidecar"
    groups = {group["id"]: group["rows"] for group in result["groups"]}
    assert groups["suggested"][0]["display"] == "sase-org/foo--bar"


def test_evaluate_template_excludes_in_lenient_and_strict() -> None:
    form = {
        "workflow_type": "gh",
        "namespace": "sase-org",
        "fields": [
            {
                "name": "add_readme",
                "label": "README",
                "kind": "bool",
                "default": "true",
            },
            {
                "name": "license",
                "label": "License",
                "kind": "search",
            },
            {
                "name": "template",
                "label": "Template",
                "kind": "line",
                "excludes": ["add_readme", "license"],
            },
        ],
    }
    lenient = evaluate_repo_creation_form(
        form, {"template": "sase-org/template"}, "lenient"
    )
    assert lenient["valid"] is True
    by_name = {field["name"]: field for field in lenient["fields"]}
    assert by_name["add_readme"]["available"] is False
    assert "Template" in by_name["add_readme"]["reason"]
    assert "license" not in lenient["effective_options"]

    strict = evaluate_repo_creation_form(
        form,
        {"template": "sase-org/template", "license": "MIT"},
        "strict",
    )
    assert strict["valid"] is False
    assert any(
        error["field"] == "license" and error["code"] == "conflict"
        for error in strict["errors"]
    )
