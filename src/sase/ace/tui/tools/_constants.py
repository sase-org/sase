"""Shared constants for tool-call artifact readers."""

TOOL_CALLS_FILENAME = "tool_calls.jsonl"
SUPPORTED_SCHEMA_VERSIONS = frozenset({1, 2, 3})
KNOWN_STATUSES = frozenset(
    {"success", "failure", "interrupted", "subagent", "pending", "incomplete"}
)
LINEAGE_METADATA_KEYS = (
    "parent_timestamp",
    "retry_of_timestamp",
    "retried_as_timestamp",
    "retry_chain_root_timestamp",
)
MAX_RELATED_ARTIFACT_DIRS = 128
MAX_RELATED_FALLBACK_SIBLINGS = 128
SLOW_TOOL_CALL_THRESHOLD_MS = 20_000
MAX_VISIBLE_SLOW_TOOL_CALLS = 8
