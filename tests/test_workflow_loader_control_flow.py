"""Tests for control flow parsing in workflow_loader."""

import pytest
from sase.xprompt.workflow_loader import _parse_workflow_step
from sase.xprompt.workflow_models import WorkflowValidationError


def test_parse_for_invalid_not_dict() -> None:
    """Test that for: must be a dict."""
    step_data = {
        "name": "bad_step",
        "bash": "echo test",
        "for": ["item1", "item2"],
    }
    with pytest.raises(WorkflowValidationError) as exc_info:
        _parse_workflow_step(step_data, 0)
    assert "'for' field must be a dict" in str(exc_info.value)


def test_parse_repeat_missing_until() -> None:
    """Test that repeat: requires until: field."""
    step_data = {
        "name": "bad_step",
        "bash": "echo test",
        "repeat": {"max": 5},
    }
    with pytest.raises(WorkflowValidationError) as exc_info:
        _parse_workflow_step(step_data, 0)
    assert "'repeat' field requires 'until' condition" in str(exc_info.value)


def test_parse_repeat_not_dict() -> None:
    """Test that repeat: must be a dict."""
    step_data = {
        "name": "bad_step",
        "bash": "echo test",
        "repeat": "{{ condition }}",
    }
    with pytest.raises(WorkflowValidationError) as exc_info:
        _parse_workflow_step(step_data, 0)
    assert "'repeat' field must be a dict" in str(exc_info.value)


def test_parse_while_short_form() -> None:
    """Test parsing while: in short form (string)."""
    step_data = {
        "name": "poll_step",
        "bash": "check_status.sh",
        "while": "{{ poll_step.pending }}",
    }
    step = _parse_workflow_step(step_data, 0)
    assert step.while_config is not None
    assert step.while_config.condition == "{{ poll_step.pending }}"
    assert step.while_config.max_iterations == 100  # Default


def test_parse_while_long_form() -> None:
    """Test parsing while: in long form (dict)."""
    step_data = {
        "name": "poll_step",
        "bash": "check_status.sh",
        "while": {
            "condition": "{{ poll_step.pending }}",
            "max": 10,
        },
    }
    step = _parse_workflow_step(step_data, 0)
    assert step.while_config is not None
    assert step.while_config.condition == "{{ poll_step.pending }}"
    assert step.while_config.max_iterations == 10


def test_parse_while_missing_condition() -> None:
    """Test that while: dict requires condition: field."""
    step_data = {
        "name": "bad_step",
        "bash": "echo test",
        "while": {"max": 10},
    }
    with pytest.raises(WorkflowValidationError) as exc_info:
        _parse_workflow_step(step_data, 0)
    assert "'while' field requires 'condition' key" in str(exc_info.value)


def test_parse_while_invalid_type() -> None:
    """Test that while: must be string or dict."""
    step_data = {
        "name": "bad_step",
        "bash": "echo test",
        "while": 123,
    }
    with pytest.raises(WorkflowValidationError) as exc_info:
        _parse_workflow_step(step_data, 0)
    assert "'while' field must be a string or dict" in str(exc_info.value)


def test_parse_join_invalid_mode() -> None:
    """Test that invalid join: mode is rejected."""
    step_data = {
        "name": "bad_step",
        "bash": "process {{ item }}",
        "for": {"item": "{{ items }}"},
        "join": "invalid_mode",
    }
    with pytest.raises(WorkflowValidationError) as exc_info:
        _parse_workflow_step(step_data, 0)
    assert "'join' must be one of" in str(exc_info.value)


def test_mutual_exclusivity_for_and_repeat() -> None:
    """Test that for: and repeat: are mutually exclusive."""
    step_data = {
        "name": "bad_step",
        "bash": "echo test",
        "for": {"item": "{{ items }}"},
        "repeat": {"until": "{{ done }}"},
    }
    with pytest.raises(WorkflowValidationError) as exc_info:
        _parse_workflow_step(step_data, 0)
    assert "can only have one of 'for', 'repeat', or 'while'" in str(exc_info.value)
