"""Memory-web substrate APIs."""

from __future__ import annotations

from .cli import handle_memory_web_list_command, handle_memory_web_show_command
from .closure import resolve_strand_closure
from .discovery import FileMemoryWebProvider, MemoryWebProvider, discover_memory_webs
from .frontmatter import parse_memory_strand, parse_web_descriptor, slug_to_keyword
from .lookup import (
    MemoryWebLookupError,
    normalize_memory_web_reference,
    resolve_memory_strand,
)
from .models import (
    MemoryStrand,
    MemoryWeb,
    MemoryWebDiscovery,
    MemoryWebDiscoveryIssue,
    MemoryWebValidationReport,
    ScopedMemoryWeb,
    WebClosureMode,
    WebRosterStyle,
    WebScope,
    WebStrandOrigin,
)
from .read_context import discover_scoped_memory_webs
from .roster import (
    END_MARKER,
    START_MARKER,
    render_managed_roster_region,
    render_strand_roster,
    render_web_body_with_roster,
    render_web_descriptor_with_roster,
)
from .scope import cross_scope_keyword_warnings, merge_memory_web_scopes
from .validation import (
    reserved_memory_web_names,
    validate_memory_web_root,
    validate_memory_webs,
)

__all__ = [
    "END_MARKER",
    "START_MARKER",
    "FileMemoryWebProvider",
    "MemoryStrand",
    "MemoryWeb",
    "MemoryWebDiscovery",
    "MemoryWebDiscoveryIssue",
    "MemoryWebLookupError",
    "MemoryWebProvider",
    "MemoryWebValidationReport",
    "ScopedMemoryWeb",
    "WebClosureMode",
    "WebRosterStyle",
    "WebScope",
    "WebStrandOrigin",
    "cross_scope_keyword_warnings",
    "discover_memory_webs",
    "discover_scoped_memory_webs",
    "handle_memory_web_list_command",
    "handle_memory_web_show_command",
    "merge_memory_web_scopes",
    "normalize_memory_web_reference",
    "parse_memory_strand",
    "parse_web_descriptor",
    "render_managed_roster_region",
    "render_strand_roster",
    "render_web_body_with_roster",
    "render_web_descriptor_with_roster",
    "reserved_memory_web_names",
    "resolve_memory_strand",
    "resolve_strand_closure",
    "slug_to_keyword",
    "validate_memory_web_root",
    "validate_memory_webs",
]
