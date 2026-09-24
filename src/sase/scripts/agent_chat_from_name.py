"""Resolve chat transcript source metadata for ``#fork`` workflows."""

from __future__ import annotations

from sase.scripts._agent_chat_from_name_cli import main
from sase.scripts._agent_chat_from_name_models import (
    ForkClanMemberSource,
    ForkExcludedAgentSessionMember,
    ForkFailure,
    ForkAgentSessionMemberSource,
    ForkSource,
)
from sase.scripts._agent_chat_from_name_resume import resolve_agent_chat_path
from sase.scripts._agent_chat_from_name_sources import resolve_agent_chat_sources

_ForkClanMemberSource = ForkClanMemberSource
_ForkExcludedAgentSessionMember = ForkExcludedAgentSessionMember
_ForkFailure = ForkFailure
_ForkAgentSessionMemberSource = ForkAgentSessionMemberSource
_ForkSource = ForkSource
_resolve_agent_chat_path = resolve_agent_chat_path
_resolve_agent_chat_sources = resolve_agent_chat_sources

__all__ = [
    "_ForkClanMemberSource",
    "_ForkExcludedAgentSessionMember",
    "_ForkFailure",
    "_ForkAgentSessionMemberSource",
    "_ForkSource",
    "_resolve_agent_chat_path",
    "_resolve_agent_chat_sources",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
