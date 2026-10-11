"""Adapter contract tests for the published project-onboarding core surface."""

from __future__ import annotations

from sase.core.project_onboarding_facade import (
    PROJECT_ONBOARDING_WIRE_SCHEMA_VERSION,
    classify_project_candidates,
    evaluate_repo_creation_form,
    plan_project_onboarding,
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


def test_plan_fresh_add_is_ready_with_stable_fingerprint() -> None:
    request = {
        "mode": "add",
        "actor": "human",
        "target": {
            "workflow_type": "gh",
            "identity_key": "github.com/sase-org/bob",
            "ref": "sase-org/bob",
            "display": "sase-org/bob",
            "checkout_dir": "/tmp/bob",
            "project_key_base": "gh_sase-org__bob",
            "project_name_base": "bob",
            "storage_policy": "separate_repo",
        },
        "requested": {"setup": "auto", "make_current": False},
    }
    facts = {
        "remote": {
            "status": "found",
            "visibility": "private",
            "can_push": True,
            "sase_managed": False,
        },
        "checkout": {"state": "absent"},
    }
    result = plan_project_onboarding(request, facts)
    assert result["schema_version"] == 1
    assert result["status"] == "ready"
    assert result["setup"]["code"] == "unmanaged_can_push"
    assert result["identity"]["key"] == "gh_sase-org__bob"
    assert result["steps"][0]["id"] == "checkout"
    assert result["steps"][0]["state"] == "pending"
    later = plan_project_onboarding(
        request,
        {
            **facts,
            "checkout": {"state": "matching"},
            "record": {
                "key": "gh_sase-org__bob",
                "name": "bob",
                "aliases": [],
                "state": "enabled",
            },
        },
    )
    assert later["intent_fingerprint"] == result["intent_fingerprint"]


def test_plan_agent_create_is_human_only() -> None:
    result = plan_project_onboarding(
        {
            "mode": "create",
            "actor": "agent",
            "target": {
                "workflow_type": "gh",
                "identity_key": "github.com/sase-org/forge",
                "ref": "sase-org/forge",
                "display": "sase-org/forge",
                "project_key_base": "gh_sase-org__forge",
                "project_name_base": "forge",
                "storage_policy": "separate_repo",
            },
            "requested": {"setup": "auto"},
            "creation": {"visibility": "private", "summary": []},
        },
        {
            "remote": {"status": "not_found"},
            "checkout": {"state": "absent"},
            "can_create": True,
        },
    )
    assert result["status"] == "blocked"
    assert any(item["code"] == "human_only" for item in result["blockers"])
    assert result["setup"]["code"] == "agent"
