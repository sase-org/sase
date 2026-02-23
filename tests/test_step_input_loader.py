"""Tests for step input loading and validation."""

import os
import tempfile

import pytest
import yaml  # type: ignore[import-untyped]
from sase.xprompt._step_input_loader import (
    load_step_input_value,
)
from sase.xprompt.models import OutputSpec
from sase.xprompt.workflow_models import WorkflowValidationError


def test_load_step_input_file_not_found() -> None:
    """Test that missing @file raises WorkflowValidationError."""
    with pytest.raises(WorkflowValidationError, match="does not exist"):
        load_step_input_value("@/nonexistent/file.yml", None)


def test_load_step_input_invalid_yaml() -> None:
    """Test that invalid YAML raises WorkflowValidationError."""
    with pytest.raises(WorkflowValidationError, match="Failed to parse"):
        load_step_input_value("{ invalid: yaml: syntax }", None)


def test_load_step_input_with_validation_failure() -> None:
    """Test loading step input with schema validation failing."""
    output_spec = OutputSpec(
        type="json_schema",
        schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
            "required": ["name"],
        },
    )
    value = '{"wrong_field": "value"}'
    with pytest.raises(WorkflowValidationError, match="validation failed"):
        load_step_input_value(value, output_spec)


def test_load_step_input_from_json_file() -> None:
    """Test loading step input from @file with JSON content."""
    import json

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"json_key": "json_value"}, f)
        file_path = f.name

    try:
        # yaml.safe_load can parse JSON too
        result = load_step_input_value(f"@{file_path}", None)
        assert result == {"json_key": "json_value"}
    finally:
        os.unlink(file_path)


# --- Auto-detected file path tests (no @ prefix) ---


def test_load_step_input_auto_detect_nonexistent_file() -> None:
    """Test that a nonexistent auto-detected file raises a clear error."""
    with pytest.raises(WorkflowValidationError, match="does not exist"):
        load_step_input_value("/nonexistent/path/file.yml", None)


def test_load_step_input_auto_detect_with_validation() -> None:
    """Test auto-detected file with schema validation."""
    output_spec = OutputSpec(
        type="json_schema",
        schema={
            "type": "object",
            "properties": {
                "name": {"type": "line"},
                "count": {"type": "int"},
            },
            "required": ["name", "count"],
        },
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
        yaml.dump({"name": "test", "count": 5}, f)
        file_path = f.name

    try:
        result = load_step_input_value(file_path, output_spec)
        assert result == {"name": "test", "count": 5}
    finally:
        os.unlink(file_path)
