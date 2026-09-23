"""Shared constants for Claude Code subscription-usage collection."""

from __future__ import annotations

from packaging.version import Version

CLAUDE_PROVIDER_NAME = "claude"
CLAUDE_USAGE_MIN_VERSION = Version("2.1.263")
CLAUDE_PASSIVE_FLUSH_SECONDS = 0.2
CLAUDE_PASSIVE_QUEUE_LIMIT = 8

__all__ = [
    "CLAUDE_PASSIVE_FLUSH_SECONDS",
    "CLAUDE_PASSIVE_QUEUE_LIMIT",
    "CLAUDE_PROVIDER_NAME",
    "CLAUDE_USAGE_MIN_VERSION",
]
