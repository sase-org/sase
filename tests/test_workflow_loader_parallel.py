"""Tests for parallel step parsing and hidden field parsing in workflow_loader."""

import pytest
from sase.xprompt.workflow_loader import _parse_workflow_step
from sase.xprompt.workflow_models import WorkflowValidationError

# ============================================================================
# Parallel step parsing tests
# ============================================================================


def test_parse_parallel_mixed_step_types() -> None:
    """Test parsing parallel: with mixed step types."""
    step_data = {
        "name": "parallel_mixed",
        "parallel": [
            {"name": "fetch", "bash": "curl https://example.com"},
            {"name": "process", "python": "print('hello')"},
        ],
    }
    step = _parse_workflow_step(step_data, 0)
    assert step.parallel_config is not None
    assert step.parallel_config.steps[0].is_bash_step()
    assert step.parallel_config.steps[1].is_python_step()


def test_parse_parallel_not_list_raises() -> None:
    """Test that parallel: must be a list."""
    step_data = {
        "name": "bad_parallel",
        "parallel": {"step_a": "echo a"},
    }
    with pytest.raises(WorkflowValidationError) as exc_info:
        _parse_workflow_step(step_data, 0)
    assert "'parallel' field must be a list" in str(exc_info.value)


def test_parse_parallel_less_than_two_steps_raises() -> None:
    """Test that parallel: requires at least 2 steps."""
    step_data = {
        "name": "bad_parallel",
        "parallel": [
            {"name": "only_one", "bash": "echo one"},
        ],
    }
    with pytest.raises(WorkflowValidationError) as exc_info:
        _parse_workflow_step(step_data, 0)
    assert "requires at least 2 steps" in str(exc_info.value)


def test_parse_parallel_duplicate_step_names_raises() -> None:
    """Test that nested steps must have unique names."""
    step_data = {
        "name": "bad_parallel",
        "parallel": [
            {"name": "duplicate", "bash": "echo a"},
            {"name": "duplicate", "bash": "echo b"},
        ],
    }
    with pytest.raises(WorkflowValidationError) as exc_info:
        _parse_workflow_step(step_data, 0)
    assert "duplicate nested step name" in str(exc_info.value)


def test_parse_parallel_nested_with_parallel_raises() -> None:
    """Test that nested steps cannot have parallel: (no nested parallelism)."""
    step_data = {
        "name": "bad_parallel",
        "parallel": [
            {"name": "step_a", "bash": "echo a"},
            {
                "name": "step_b",
                "parallel": [
                    {"name": "inner_a", "bash": "echo inner"},
                    {"name": "inner_b", "bash": "echo inner2"},
                ],
            },
        ],
    }
    with pytest.raises(WorkflowValidationError) as exc_info:
        _parse_workflow_step(step_data, 0)
    assert "cannot have" in str(exc_info.value)
    assert "'parallel'" in str(exc_info.value)


def test_parse_parallel_nested_with_hitl_raises() -> None:
    """Test that nested steps cannot have hitl: true."""
    step_data = {
        "name": "bad_parallel",
        "parallel": [
            {"name": "step_a", "bash": "echo a"},
            {"name": "step_b", "bash": "echo b", "hitl": True},
        ],
    }
    with pytest.raises(WorkflowValidationError) as exc_info:
        _parse_workflow_step(step_data, 0)
    assert "cannot have 'hitl: true'" in str(exc_info.value)


def test_parse_parallel_with_while_raises() -> None:
    """Test that parallel: cannot combine with while:."""
    step_data = {
        "name": "bad_parallel",
        "parallel": [
            {"name": "step_a", "bash": "echo a"},
            {"name": "step_b", "bash": "echo b"},
        ],
        "while": "{{ pending }}",
    }
    with pytest.raises(WorkflowValidationError) as exc_info:
        _parse_workflow_step(step_data, 0)
    assert "cannot combine 'parallel' with" in str(exc_info.value)
    assert "'while'" in str(exc_info.value)


def test_parse_parallel_mutually_exclusive_with_agent() -> None:
    """Test that parallel: is mutually exclusive with agent:."""
    step_data = {
        "name": "bad_step",
        "agent": "Do something",
        "parallel": [
            {"name": "step_a", "bash": "echo a"},
            {"name": "step_b", "bash": "echo b"},
        ],
    }
    with pytest.raises(WorkflowValidationError) as exc_info:
        _parse_workflow_step(step_data, 0)
    assert "can only have one of" in str(exc_info.value)


# ============================================================================
# Hidden step field tests
# ============================================================================
