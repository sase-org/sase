"""SASE-native message types for the LLM provider compatibility surface.

These intentionally implement only the small subset of LangChain message
behavior that SASE relies on:

- construction with ``content=...``
- ``.content`` access
- ``isinstance(msg, HumanMessage)`` routing in the deprecated Gemini wrapper
- list content compatibility with :func:`sase.content.ensure_str_content`

SASE no longer depends on ``langchain-core``; do not reintroduce LangChain
semantics here. These are the public message objects returned by the
``invoke_agent()`` compatibility surface.
"""

from dataclasses import dataclass
from typing import Any

#: Message content is either a plain string or a list of content parts, mirroring
#: the shape SASE has historically accepted from LLM responses.
MessageContent = str | list[str | dict[Any, Any]]


@dataclass(frozen=True)
class BaseMessage:
    """Immutable base message carrying string-or-list ``content``."""

    content: MessageContent


@dataclass(frozen=True)
class AIMessage(BaseMessage):
    """An assistant/agent message response."""


@dataclass(frozen=True)
class HumanMessage(BaseMessage):
    """A human/user message."""
