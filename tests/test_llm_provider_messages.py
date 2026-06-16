"""Tests for the SASE-native LLM provider message types."""

import dataclasses

import pytest

from sase.content import ensure_str_content
from sase.llm_provider import AIMessage, BaseMessage, HumanMessage
from sase.llm_provider.messages import AIMessage as DirectAIMessage


def test_messages_reexported_from_package() -> None:
    """The package re-export and module definition are the same class."""
    assert AIMessage is DirectAIMessage


def test_ai_message_content_access() -> None:
    """AIMessage is constructed with content= and exposes .content."""
    msg = AIMessage(content="hello")
    assert msg.content == "hello"


def test_human_message_content_access() -> None:
    """HumanMessage is constructed with content= and exposes .content."""
    msg = HumanMessage(content="ask")
    assert msg.content == "ask"


def test_messages_are_base_message_subclasses() -> None:
    """AIMessage and HumanMessage participate in isinstance routing."""
    ai = AIMessage(content="a")
    human = HumanMessage(content="h")
    assert isinstance(ai, BaseMessage)
    assert isinstance(human, BaseMessage)
    # The two message kinds are distinguishable for routing.
    assert not isinstance(ai, HumanMessage)
    assert not isinstance(human, AIMessage)


def test_messages_are_immutable() -> None:
    """Message instances are frozen and cannot be mutated."""
    msg = AIMessage(content="frozen")
    with pytest.raises(dataclasses.FrozenInstanceError):
        msg.content = "changed"  # type: ignore[misc]


def test_messages_equal_by_value() -> None:
    """Frozen dataclasses compare equal by type and content."""
    assert AIMessage(content="x") == AIMessage(content="x")
    assert AIMessage(content="x") != HumanMessage(content="x")


def test_list_content_compatible_with_ensure_str_content() -> None:
    """List content is supported and normalizes via ensure_str_content."""
    msg = AIMessage(content=["part1", {"key": "value"}])
    result = ensure_str_content(msg.content)
    assert isinstance(result, str)
    assert "part1" in result
