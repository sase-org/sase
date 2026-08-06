"""Tests for the xprompt workflow JSON schema."""

import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft7Validator


import pytest

pytestmark = pytest.mark.contract

ROOT = Path(__file__).resolve().parents[1]


def _validator() -> Draft7Validator:
    schema = json.loads(
        (ROOT / "src/sase/xprompts/workflow.schema.json").read_text(encoding="utf-8")
    )
    Draft7Validator.check_schema(schema)
    return Draft7Validator(schema)


def _load_xprompt_workflow(name: str) -> dict[str, Any]:
    data = yaml.safe_load(
        (ROOT / "src/sase/xprompts" / name).read_text(encoding="utf-8")
    )
    assert isinstance(data, dict)
    return data


def _is_valid(instance: dict[str, Any]) -> bool:
    return not list(_validator().iter_errors(instance))


def test_checked_in_workflows_with_finally_and_artifact_validate() -> None:
    assert _is_valid(_load_xprompt_workflow("git.yml"))
    assert _is_valid(_load_xprompt_workflow("json.yml"))


def test_workflow_schema_accepts_descriptions() -> None:
    assert _is_valid(
        {
            "description": "Run a described workflow.",
            "input": [
                {
                    "name": "prompt",
                    "type": "text",
                    "description": "User request for the workflow.",
                }
            ],
            "xprompts": {
                "_local": {
                    "description": "Local helper prompt.",
                    "input": {
                        "target": {
                            "type": "word",
                            "description": "Target name for the helper.",
                        }
                    },
                    "content": "Review {{ target }}",
                }
            },
            "steps": [{"name": "main", "prompt_part": "#_local"}],
        }
    )


def test_workflow_schema_accepts_repeatable_input_metadata() -> None:
    assert _is_valid(
        {
            "input": {
                "names": {
                    "type": "agent",
                    "default": None,
                    "repeatable": True,
                }
            },
            "steps": [{"name": "main", "prompt_part": "{{ names }}"}],
        }
    )
    assert not _is_valid(
        {
            "input": {"names": {"type": "agent", "repeatable": "yes"}},
            "steps": [{"name": "main", "prompt_part": "{{ names }}"}],
        }
    )


def test_finally_is_only_allowed_on_top_level_steps() -> None:
    assert _is_valid(
        {
            "steps": [
                {"name": "work", "bash": "echo work"},
                {"name": "cleanup", "bash": "echo clean", "finally": True},
            ]
        }
    )

    assert not _is_valid(
        {"steps": [{"name": "inject", "prompt_part": "body", "finally": True}]}
    )
    assert not _is_valid(
        {
            "steps": [
                {
                    "name": "parallel_work",
                    "parallel": [
                        {"name": "a", "bash": "echo a", "finally": True},
                        {"name": "b", "bash": "echo b"},
                    ],
                }
            ]
        }
    )


def test_artifact_stdout_is_only_allowed_on_top_level_bash_python_steps() -> None:
    assert _is_valid(
        {"steps": [{"name": "capture", "bash": "echo data", "artifact": "stdout"}]}
    )
    assert _is_valid(
        {
            "steps": [
                {"name": "capture", "python": "print('data')", "artifact": "stdout"}
            ]
        }
    )

    assert not _is_valid(
        {"steps": [{"name": "ask", "prompt": "question", "artifact": "stdout"}]}
    )
    assert not _is_valid(
        {"steps": [{"name": "inject", "prompt_part": "body", "artifact": "stdout"}]}
    )
    assert not _is_valid(
        {
            "steps": [
                {
                    "name": "parallel_work",
                    "parallel": [
                        {"name": "a", "bash": "echo a", "artifact": "stdout"},
                        {"name": "b", "bash": "echo b"},
                    ],
                }
            ]
        }
    )
