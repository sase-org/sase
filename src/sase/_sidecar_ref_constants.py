"""Constants shared by sidecar ref policy modules."""

from __future__ import annotations

from sase.sdd._store_types import (
    AGENTS_SIDECAR_ROLE,
    BEADS_SIDECAR_ROLE,
    PLANS_SIDECAR_ROLE,
)

REF_CONFIG_KEY = "ref"
REF_USE_CONFIG_KEY = "use"
REF_ICON_CONFIG_KEY = "icon"
REF_KIND_CONFIG_KEY = "kind"
REF_EXPANSION_FORMAT_CONFIG_KEY = "expansion_format"
REF_PROPERTIES_CONFIG_KEY = "properties"
REF_DETAIL_CONFIG_KEY = "detail"
REF_IDENTITY_CONFIG_KEY = "identity"
REF_INVENTORY_CONFIG_KEY = "inventory"
REF_PUBLICATION_CONFIG_KEY = "publication"
REF_CAPABILITIES_CONFIG_KEY = "capabilities"
REF_RELATIONS_CONFIG_KEY = "relations"
REF_GROUPING_CONFIG_KEY = "grouping"
REF_PANE_CONFIG_KEY = "pane"
REF_XPROMPT_CONFIG_KEY = "xprompt"
REF_FILTERS_CONFIG_KEY = "filters"
REF_PATH_GLOBS_CONFIG_KEY = "path_globs"
REF_INVENTORY_GLOBS_CONFIG_KEY = "globs"

DEFAULT_DOCUMENT_REF_PATH_GLOBS: tuple[str, ...] = ("**/*.md",)
SIDECAR_REF_CONFIG_SOURCE_PREFIX = "sidecar_ref_config:"
DOCUMENT_REF_PROVIDER_SPEC_SCHEMA_VERSION = 1
DEFAULT_DOCUMENT_REF_EXPANSION_FORMAT = (
    "the {repo_relative_path} file in the {sidecar_role} sidecar repo"
)
DEFAULT_DOCUMENT_TAB_ICON = "◆"

# A subset of the Rust expansion vocabulary (sase-core's
# artifact_ref/expansion.rs); the excluded names (project, repository,
# captured_revision, captured_digest, logical_path) have no document-ref
# binding and must be rejected rather than rendered empty.
DOCUMENT_REF_EXPANSION_PLACEHOLDERS = frozenset(
    {
        "kind",
        "argument",
        "canonical_argument",
        "display_label",
        "repo_relative_path",
        "sidecar_role",
        "checkout_path",
    }
)
DOCUMENT_REF_PATH_PLACEHOLDERS = frozenset({"checkout_path"})

BUILTIN_SIDECAR_REF_KIND = {
    PLANS_SIDECAR_ROLE: "plan",
    BEADS_SIDECAR_ROLE: "bead",
    AGENTS_SIDECAR_ROLE: "agent",
}
KNOWN_REF_CONFIG_KEYS = frozenset(
    {
        REF_USE_CONFIG_KEY,
        REF_ICON_CONFIG_KEY,
        REF_KIND_CONFIG_KEY,
        REF_EXPANSION_FORMAT_CONFIG_KEY,
        REF_PROPERTIES_CONFIG_KEY,
        REF_DETAIL_CONFIG_KEY,
        REF_IDENTITY_CONFIG_KEY,
        REF_INVENTORY_CONFIG_KEY,
        REF_PUBLICATION_CONFIG_KEY,
        REF_CAPABILITIES_CONFIG_KEY,
        REF_RELATIONS_CONFIG_KEY,
        REF_GROUPING_CONFIG_KEY,
        REF_PANE_CONFIG_KEY,
        REF_FILTERS_CONFIG_KEY,
        REF_XPROMPT_CONFIG_KEY,
    }
)
