from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from sase.memory.read_log import (
    AgentIdentity,
    AgentIdentityError,
    FrontmatterStripResult,
    MemoryReadAgentSummary,
    MemoryReadContent,
    MemoryReadError,
    MemoryReadEvent,
    MemoryReadPathError,
    MemoryReadPathSummary,
    ValidatedMemoryPath,
    append_memory_read_event,
    build_memory_read_event,
    discover_agent_identity,
    filter_memory_read_events,
    memory_read_log_path,
    normalize_read_reason,
    read_memory_content,
    read_memory_read_events,
    require_agent_identity,
    strip_leading_frontmatter,
    summarize_memory_reads_by_agent,
    summarize_memory_reads_by_path,
    validate_memory_read_path,
)

if TYPE_CHECKING:
    from sase.memory.link_resolve import (
        MemoryLinkTarget as MemoryLinkTarget,
        MemoryNoteLinkTarget as MemoryNoteLinkTarget,
        MemoryStrandLinkTarget as MemoryStrandLinkTarget,
        MemoryWebDescriptorLinkTarget as MemoryWebDescriptorLinkTarget,
        UnresolvedMemoryLinkTarget as UnresolvedMemoryLinkTarget,
        resolve_memory_link_target as resolve_memory_link_target,
    )
    from sase.memory.links import (
        MemoryLink as MemoryLink,
        scan_memory_links as scan_memory_links,
    )

_LAZY_EXPORTS = {
    "MemoryLink": "sase.memory.links",
    "MemoryLinkTarget": "sase.memory.link_resolve",
    "MemoryNoteLinkTarget": "sase.memory.link_resolve",
    "MemoryStrandLinkTarget": "sase.memory.link_resolve",
    "MemoryWebDescriptorLinkTarget": "sase.memory.link_resolve",
    "UnresolvedMemoryLinkTarget": "sase.memory.link_resolve",
    "resolve_memory_link_target": "sase.memory.link_resolve",
    "scan_memory_links": "sase.memory.links",
}


def __getattr__(name: str) -> Any:
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})


# PEP 562 entry points are called by Python, not by normal in-file code.
_PEP562_HOOKS = (__getattr__, __dir__)


__all__ = [
    "AgentIdentity",
    "AgentIdentityError",
    "FrontmatterStripResult",
    "MemoryLink",
    "MemoryLinkTarget",
    "MemoryNoteLinkTarget",
    "MemoryReadAgentSummary",
    "MemoryReadContent",
    "MemoryReadError",
    "MemoryReadEvent",
    "MemoryReadPathError",
    "MemoryReadPathSummary",
    "MemoryStrandLinkTarget",
    "MemoryWebDescriptorLinkTarget",
    "UnresolvedMemoryLinkTarget",
    "ValidatedMemoryPath",
    "append_memory_read_event",
    "build_memory_read_event",
    "discover_agent_identity",
    "filter_memory_read_events",
    "memory_read_log_path",
    "normalize_read_reason",
    "read_memory_content",
    "read_memory_read_events",
    "require_agent_identity",
    "resolve_memory_link_target",
    "scan_memory_links",
    "strip_leading_frontmatter",
    "summarize_memory_reads_by_agent",
    "summarize_memory_reads_by_path",
    "validate_memory_read_path",
]
