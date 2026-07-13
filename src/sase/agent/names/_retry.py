"""Retry-derived agent-name allocation."""

from __future__ import annotations


def allocate_retry_name(
    base: str,
    *,
    reserved: set[str] | None = None,
) -> str:
    """Return the first available rendering of ``<base>.r@``."""
    from sase.agent.names._templates import allocate_agent_name_template

    return allocate_agent_name_template(
        retry_agent_name_template(base),
        reserved=reserved,
    )


def retry_agent_name_template(base: str) -> str:
    """Return the template used for retry-derived agent names."""
    return f"{base}.r@"
