"""Presentation-neutral agent status formatting helpers for integrations."""

from __future__ import annotations

from sase.agent.status_buckets import AGENT_STATUS_BUCKET_GLYPHS

__all__ = [
    "agent_status_bucket_glyph",
    "status_bucket_header",
]


def agent_status_bucket_glyph(bucket: str) -> str:
    """Return the shared glyph for a status bucket."""
    return AGENT_STATUS_BUCKET_GLYPHS.get(bucket, "")


# symvision: https://github.com/sase-org/sase-telegram.git
def status_bucket_header(bucket: str, count: int) -> str:
    """Return the shared plain-text status bucket header."""
    glyph = agent_status_bucket_glyph(bucket)
    prefix = f"{glyph} " if glyph else ""
    return f"{prefix}{bucket} ({count})"
