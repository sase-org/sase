"""Schema coverage for project-owned tools and operational tool_runs."""

from __future__ import annotations

import pytest
import yaml
from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError

from tests._config_schema_helpers import REPO_ROOT, schema


def test_project_sase_yml_matches_public_schema() -> None:
    validator = Draft7Validator(schema())
    project_config = yaml.safe_load(
        (REPO_ROOT / "sase" / "sase.yml").read_text(encoding="utf-8")
    )
    validator.validate(project_config)


def test_config_schema_accepts_named_tool_catalog() -> None:
    validator = Draft7Validator(schema())
    validator.validate(
        {
            "tools": {
                "check": {
                    "argv": ["just", "check"],
                    "description": "check",
                    "stages": "run_silent",
                    "inputs": ["Justfile"],
                    "env": ["SASE_PYTEST_WORKERS"],
                    "args": "deny",
                    "fingerprint": {
                        "repos": ["sase"],
                        "toolchain": {"python": ["python", "--version"]},
                    },
                }
            }
        }
    )


def test_config_schema_rejects_unknown_tool_field() -> None:
    with pytest.raises(ValidationError):
        Draft7Validator(schema()).validate(
            {"tools": {"check": {"argv": ["just", "check"], "shell": True}}}
        )


def test_config_schema_rejects_empty_tool_argv() -> None:
    with pytest.raises(ValidationError):
        Draft7Validator(schema()).validate({"tools": {"check": {"argv": []}}})


def test_config_schema_rejects_unknown_tool_runs_field() -> None:
    with pytest.raises(ValidationError):
        Draft7Validator(schema()).validate(
            {"tool_runs": {"summary_days": 1, "extra": 1}}
        )


def test_config_schema_rejects_non_positive_tool_runs_days() -> None:
    with pytest.raises(ValidationError):
        Draft7Validator(schema()).validate({"tool_runs": {"summary_days": 0}})


def test_default_config_tool_runs_match_schema_defaults() -> None:
    public_schema = schema()
    defaults = yaml.safe_load(
        (REPO_ROOT / "src/sase/default_config.yml").read_text(encoding="utf-8")
    )
    properties = public_schema["definitions"]["toolRuns"]["properties"]
    actual = defaults["tool_runs"]
    assert actual["summary_days"] == properties["summary_days"]["default"]
    assert actual["detail_days"] == properties["detail_days"]["default"]
    assert actual["log_days"] == properties["log_days"]["default"]
    assert actual["log_max_bytes"] == properties["log_max_bytes"]["default"]
    assert actual["run_log_max_bytes"] == properties["run_log_max_bytes"]["default"]
    assert actual["event_max_bytes"] == properties["event_max_bytes"]["default"]
