"""Typed models shared by tmux Agent catalog assembly and presentation."""

from __future__ import annotations

from dataclasses import dataclass

from sase.llm_provider.provider_disable import TemporaryProviderDisable


@dataclass(frozen=True)
class TmuxAgentEntry:
    """One provider's fully resolved row in the tmux Agent catalog."""

    provider: str
    display_name: str
    vendor: str
    color: str
    key: str
    binary: str
    executable: str | None
    installed: bool
    install_hint: str
    routing_disabled: TemporaryProviderDisable | None
    argv: tuple[str, ...]
    env: tuple[tuple[str, str], ...]
    effort: str | None
    effort_skipped: str | None
    bypass: bool


@dataclass(frozen=True)
class TmuxAgentCatalog:
    """The full tmux Agent catalog for one launch directory."""

    entries: tuple[TmuxAgentEntry, ...]
    default_provider: str | None
    directory: str


__all__ = [
    "TmuxAgentCatalog",
    "TmuxAgentEntry",
]
