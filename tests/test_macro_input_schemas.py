"""Generated macro input-type JSON Schema tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft7Validator

from sase.config.inventory import load_config_schema
from sase.macro.input_schemas import (
    PLUGIN_QUALIFIED_TYPE_PATTERN,
    macro_input_schemas_drift,
    workflow_input_definitions_block,
)


ROOT = Path(__file__).resolve().parents[1]


def _workflow_schema() -> dict[str, Any]:
    return json.loads(
        (ROOT / "src/sase/macros/workflow.schema.json").read_text(encoding="utf-8")
    )


def test_advertised_catalog_names_include_enum_code_agent_and_aliases() -> None:
    type_schema = workflow_input_definitions_block()["oneOf"][0]["items"]["properties"][
        "type"
    ]
    names = type_schema["anyOf"][0]["enum"]
    assert names == [
        "word",
        "line",
        "text",
        "path",
        "int",
        "integer",
        "float",
        "bool",
        "boolean",
        "code",
        "enum",
        "agent",
    ]
    assert type_schema["anyOf"][1]["const"] == "string"
    assert type_schema["anyOf"][1]["deprecated"] is True
    assert "string" not in names


def test_shipped_macro_input_schema_blocks_have_no_drift() -> None:
    workflow = _workflow_schema()
    config = load_config_schema()

    assert macro_input_schemas_drift(workflow, config) is None

    mutated = copy.deepcopy(workflow)
    mutated["definitions"]["inputDefinitions"]["description"] = "wrong"
    assert macro_input_schemas_drift(mutated, config) is not None


def test_generated_type_field_accepts_plugin_pattern_and_deprecated_string() -> None:
    schema = workflow_input_definitions_block()
    type_schema = schema["oneOf"][0]["items"]["properties"]["type"]
    branches = type_schema["anyOf"]
    assert branches[0]["enum"] == [
        "word",
        "line",
        "text",
        "path",
        "int",
        "integer",
        "float",
        "bool",
        "boolean",
        "code",
        "enum",
        "agent",
    ]
    assert branches[1]["const"] == "string"
    assert branches[1]["deprecated"] is True
    assert branches[2]["pattern"] == PLUGIN_QUALIFIED_TYPE_PATTERN

    validator = Draft7Validator(schema)
    instance = [
        {"name": "mode", "type": "enum", "choices": ["wip", "draft"]},
        {"name": "legacy", "type": "string"},
        {"name": "edition", "type": "sase-research-artifacts@audio_edition"},
        {
            "name": "status",
            "type": "enum",
            "choices": [
                {"value": "ready", "label": "Ready", "description": "Ready"},
            ],
        },
    ]
    assert not list(validator.iter_errors(instance))
    assert list(validator.iter_errors([{"name": "mode", "type": "enmu"}]))


def test_bundled_pr_and_eval_workflows_match_generated_schema() -> None:
    schema = _workflow_schema()
    Draft7Validator.check_schema(schema)
    validator = Draft7Validator(schema)
    for name in ("pr.yml", "eval_ifs_loops.yml"):
        data = yaml.safe_load(
            (ROOT / "src/sase/macros" / name).read_text(encoding="utf-8")
        )
        assert isinstance(data, dict)
        assert not list(validator.iter_errors(data)), name
