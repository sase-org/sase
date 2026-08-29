"""Public facade for auditable ``sase memory read`` access."""

from __future__ import annotations

from sase.agent.identity import (
    AgentIdentity,
    AgentIdentityError,
    AgentIdentitySource,
    agent_name_from_meta,
    discover_agent_identity,
    resolve_audit_identity,
)
from sase.memory._read_log_events import (
    append_memory_read_event,
    build_memory_read_batch_event,
    build_memory_read_event,
    filter_memory_read_events,
    memory_read_log_path,
    normalize_read_reason,
    read_memory_read_events,
    require_agent_identity,
    summarize_memory_reads_by_agent,
    summarize_memory_reads_by_path,
)
from sase.memory._read_log_models import (
    READ_LOG_SCHEMA_VERSION,
    FrontmatterStripResult,
    MemoryReadAgentSummary,
    MemoryReadContent,
    MemoryReadError,
    MemoryReadEvent,
    MemoryReadKind,
    MemoryReadPathError,
    MemoryReadPathSummary,
    ValidatedMemoryPath,
)
from sase.memory._read_log_paths import (
    read_memory_content,
    strip_leading_frontmatter,
    validate_memory_read_path,
)

__all__ = [
    "READ_LOG_SCHEMA_VERSION",
    "AgentIdentity",
    "AgentIdentityError",
    "AgentIdentitySource",
    "FrontmatterStripResult",
    "MemoryReadAgentSummary",
    "MemoryReadContent",
    "MemoryReadError",
    "MemoryReadEvent",
    "MemoryReadKind",
    "MemoryReadPathError",
    "MemoryReadPathSummary",
    "ValidatedMemoryPath",
    "agent_name_from_meta",
    "append_memory_read_event",
    "build_memory_read_batch_event",
    "build_memory_read_event",
    "discover_agent_identity",
    "filter_memory_read_events",
    "memory_read_log_path",
    "normalize_read_reason",
    "read_memory_content",
    "read_memory_read_events",
    "require_agent_identity",
    "resolve_audit_identity",
    "strip_leading_frontmatter",
    "summarize_memory_reads_by_agent",
    "summarize_memory_reads_by_path",
    "validate_memory_read_path",
]
