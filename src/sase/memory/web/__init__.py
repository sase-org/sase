"""Memory-web substrate APIs."""

from __future__ import annotations

from .cli import handle_memory_web_list_command, handle_memory_web_show_command
from .closure import resolve_strand_closure
from .discovery import FileMemoryWebProvider, MemoryWebProvider, discover_memory_webs
from .frontmatter import (
    parse_memory_strand,
    parse_web_descriptor,
    render_strand_frontmatter,
    slug_to_keyword,
)
from .generated import (
    GeneratedMemoryWebProvider,
    GeneratedStrandSource,
    GeneratedWebSource,
)
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
    WebSource,
    WebStrandOrigin,
)
from .mutation import (
    MemoryConflictError,
    create_memory_strand,
    delete_memory_strand,
    memory_strand_digest,
)
from .mutation_models import (
    MemoryStrandDraft,
    MemoryStrandDraftValidation,
    MemoryStrandMutationError,
    MemoryStrandMutationOutcome,
    MemoryStrandValidationError,
)
from .mutation_validate import validate_memory_strand_draft
from .read_context import discover_scoped_memory_webs
from .roster import (
    END_MARKER,
    START_MARKER,
    render_managed_roster_region,
    render_strand_roster,
    render_web_body_with_roster,
    render_web_descriptor_with_roster,
    strip_managed_roster_markers,
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
    "GeneratedMemoryWebProvider",
    "GeneratedStrandSource",
    "GeneratedWebSource",
    "MemoryConflictError",
    "MemoryStrand",
    "MemoryStrandDraft",
    "MemoryStrandDraftValidation",
    "MemoryStrandMutationError",
    "MemoryStrandMutationOutcome",
    "MemoryStrandValidationError",
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
    "WebSource",
    "WebStrandOrigin",
    "create_memory_strand",
    "cross_scope_keyword_warnings",
    "delete_memory_strand",
    "discover_memory_webs",
    "discover_scoped_memory_webs",
    "handle_memory_web_list_command",
    "handle_memory_web_show_command",
    "memory_strand_digest",
    "merge_memory_web_scopes",
    "normalize_memory_web_reference",
    "parse_memory_strand",
    "parse_web_descriptor",
    "render_managed_roster_region",
    "render_strand_frontmatter",
    "render_strand_roster",
    "render_web_body_with_roster",
    "render_web_descriptor_with_roster",
    "reserved_memory_web_names",
    "resolve_memory_strand",
    "resolve_strand_closure",
    "slug_to_keyword",
    "strip_managed_roster_markers",
    "validate_memory_strand_draft",
    "validate_memory_web_root",
    "validate_memory_webs",
]
