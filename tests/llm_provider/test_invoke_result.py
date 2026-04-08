"""Tests for InvokeResult and token metric recording in invoke_agent."""

from sase.llm_provider.types import InvokeResult


def test_invoke_result_with_usage() -> None:
    """InvokeResult carries content and usage data."""
    usage = {"input_tokens": 100, "output_tokens": 50}
    result = InvokeResult(content="hello", usage=usage)
    assert result.content == "hello"
    assert result.usage == usage


def test_invoke_result_without_usage() -> None:
    """InvokeResult defaults usage to None."""
    result = InvokeResult(content="hello")
    assert result.content == "hello"
    assert result.usage is None


def test_invoke_result_is_frozen() -> None:
    """InvokeResult is immutable."""
    result = InvokeResult(content="hello")
    raised = False
    try:
        result.content = "world"  # type: ignore[misc]
    except AttributeError:
        raised = True
    assert raised, "Expected FrozenInstanceError"
