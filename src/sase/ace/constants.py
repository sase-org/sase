"""Constants used across the ace package."""

# Default time in seconds after which a hook or workflow is considered a zombie (2 hours)
DEFAULT_ZOMBIE_TIMEOUT_SECONDS = 2 * 60 * 60

# Default required hooks for Mercurial ChangeSpecs (order matters).
# Only used when detect_vcs_family() returns "hg"; git repos get no defaults.
# - "!" prefix: skip fix-hook hints on failure
# - "$" prefix: skip running for proposal entries (e.g., "1a")
# Can be overridden via vcs_provider.default_hooks in sase.yml.
_DEFAULT_REQUIRED_HOOKS = (
    "!$sase_hg_presubmit",
    "$sase_hg_lint",
)
