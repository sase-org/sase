"""Names, defaults, and descriptions for built-in model aliases."""

from __future__ import annotations

# Builtin-role overrides are configured under
# ``llm_provider.model_aliases.builtin``; user-created aliases live under
# ``llm_provider.model_aliases.custom`` so they can carry required descriptions.
# On top of the configured maps, SASE exposes a fixed set of *implicit* special
# aliases that always resolve, even when the user has not defined them:
#
#   - ``default``: the model used when a prompt has no explicit ``%model``.
#   - ``coder`` / ``<provider>_coder``: coder follow-up roles.
#   - ``epic_lander`` / ``big_epic_lander`` /
#     ``<size>_phase_worker`` / ``smart`` / ``smartest`` /
#     ``cheap`` / ``cheaper`` / ``cheapest``: bead/epic roles.
#
# Most roles fall back to another alias (ultimately ``@default``) when they are
# not explicitly configured. ``smartest`` and ``cheapest`` instead own ordered
# provider fallbacks, while ``cheap`` and ``cheaper`` own load-balanced pools.
# ``default`` itself falls back to the configured or autodetected provider's
# tier default.

#: The implicit "default" alias name (used for no-``%model`` launches).
DEFAULT_MODEL_ALIAS_NAME = "default"

#: The implicit "coder" alias name (``<provider>_coder`` falls back to this).
CODER_MODEL_ALIAS_NAME = "coder"

#: Suffix that turns a provider name into its ``<provider>_coder`` alias.
PROVIDER_CODER_ALIAS_SUFFIX = "_coder"

#: Legacy epic-creator alias name. It is no longer implicit or used by SASE,
#: but configured builtin entries remain accepted for compatibility.
EPIC_CREATOR_MODEL_ALIAS_NAME = "epic_creator"

#: The implicit "epic_lander" role alias (epic land follow-up default).
EPIC_LANDER_MODEL_ALIAS_NAME = "epic_lander"

#: The implicit large-epic lander role alias (threshold-selected follow-up).
BIG_EPIC_LANDER_MODEL_ALIAS_NAME = "big_epic_lander"

#: The implicit extra-small-phase role alias.
XSMALL_PHASE_WORKER_MODEL_ALIAS_NAME = "xsmall_phase_worker"

#: The implicit small-phase role alias.
SMALL_PHASE_WORKER_MODEL_ALIAS_NAME = "small_phase_worker"

#: The implicit medium-phase role alias.
MEDIUM_PHASE_WORKER_MODEL_ALIAS_NAME = "medium_phase_worker"

#: Concrete default for the implicit medium-phase role alias.
MEDIUM_PHASE_WORKER_MODEL_ALIAS_DEFAULT = "codex/gpt-5.6-sol@high"

#: The implicit large-phase role alias.
LARGE_PHASE_WORKER_MODEL_ALIAS_NAME = "large_phase_worker"

#: The implicit extra-large-phase role alias.
XLARGE_PHASE_WORKER_MODEL_ALIAS_NAME = "xlarge_phase_worker"

#: The implicit "smart" high-capability alias.
SMART_MODEL_ALIAS_NAME = "smart"

#: The implicit "smartest" highest-capability alias.
SMARTEST_MODEL_ALIAS_NAME = "smartest"

#: Provider-aware ordered fallback for the implicit smartest alias.
SMARTEST_MODEL_ALIAS_DEFAULT = "claude/claude-fable-5 || codex/gpt-5.6-sol"

#: The implicit load-balanced small-phase alias.
CHEAP_MODEL_ALIAS_NAME = "cheap"

#: Default target pool for the implicit :data:`CHEAP_MODEL_ALIAS_NAME`.
CHEAP_MODEL_ALIAS_DEFAULT = "claude/opus@medium | codex/gpt-5.5"

#: The implicit load-balanced extra-small-phase alias.
CHEAPER_MODEL_ALIAS_NAME = "cheaper"

#: Default target pool for the implicit :data:`CHEAPER_MODEL_ALIAS_NAME`.
CHEAPER_MODEL_ALIAS_DEFAULT = "claude/sonnet | codex/gpt-5.3-codex-spark"

#: The implicit lowest-cost alias.
CHEAPEST_MODEL_ALIAS_NAME = "cheapest"

#: Provider-aware ordered fallback for :data:`CHEAPEST_MODEL_ALIAS_NAME`.
CHEAPEST_MODEL_ALIAS_DEFAULT = "claude/haiku || codex/gpt-5.3-codex-spark"

#: Fixed implicit role aliases (besides ``default``) mapped to the alias each
#: falls back to when the user has not configured it explicitly.
ROLE_ALIAS_FALLBACKS: dict[str, str] = {
    CODER_MODEL_ALIAS_NAME: f"@{DEFAULT_MODEL_ALIAS_NAME}",
    EPIC_LANDER_MODEL_ALIAS_NAME: f"@{DEFAULT_MODEL_ALIAS_NAME}",
    BIG_EPIC_LANDER_MODEL_ALIAS_NAME: f"@{SMARTEST_MODEL_ALIAS_NAME}",
    XSMALL_PHASE_WORKER_MODEL_ALIAS_NAME: f"@{CHEAPER_MODEL_ALIAS_NAME}",
    SMALL_PHASE_WORKER_MODEL_ALIAS_NAME: f"@{CHEAP_MODEL_ALIAS_NAME}",
    LARGE_PHASE_WORKER_MODEL_ALIAS_NAME: f"@{SMART_MODEL_ALIAS_NAME}",
    XLARGE_PHASE_WORKER_MODEL_ALIAS_NAME: f"@{SMARTEST_MODEL_ALIAS_NAME}",
    SMART_MODEL_ALIAS_NAME: f"@{DEFAULT_MODEL_ALIAS_NAME}",
}

#: Concrete/selector defaults for implicit aliases that do not alias a role.
IMPLICIT_ALIAS_TARGETS: dict[str, str] = {
    MEDIUM_PHASE_WORKER_MODEL_ALIAS_NAME: MEDIUM_PHASE_WORKER_MODEL_ALIAS_DEFAULT,
    SMARTEST_MODEL_ALIAS_NAME: SMARTEST_MODEL_ALIAS_DEFAULT,
    CHEAP_MODEL_ALIAS_NAME: CHEAP_MODEL_ALIAS_DEFAULT,
    CHEAPER_MODEL_ALIAS_NAME: CHEAPER_MODEL_ALIAS_DEFAULT,
    CHEAPEST_MODEL_ALIAS_NAME: CHEAPEST_MODEL_ALIAS_DEFAULT,
}

#: Configured builtin names that retain role presentation for compatibility.
LEGACY_BUILTIN_ALIAS_NAMES = {EPIC_CREATOR_MODEL_ALIAS_NAME}

#: User-facing descriptions for implicit aliases.
ROLE_ALIAS_DESCRIPTIONS: dict[str, str] = {
    DEFAULT_MODEL_ALIAS_NAME: (
        "Model used when a prompt has no %model directive; every other alias "
        "ultimately falls back to it."
    ),
    CODER_MODEL_ALIAS_NAME: (
        "Coder follow-up agents launched from plans (fallback for every "
        "<provider>_coder alias)."
    ),
    EPIC_LANDER_MODEL_ALIAS_NAME: (
        "Epic land agents that finalize and submit an epic."
    ),
    BIG_EPIC_LANDER_MODEL_ALIAS_NAME: (
        "Epic land agents selected for plans at or above the configured "
        "phase-count threshold."
    ),
    XSMALL_PHASE_WORKER_MODEL_ALIAS_NAME: (
        "Extra-small bead phase agents that implement the simplest tasks directly."
    ),
    SMALL_PHASE_WORKER_MODEL_ALIAS_NAME: (
        "Small bead phase agents that implement directly."
    ),
    MEDIUM_PHASE_WORKER_MODEL_ALIAS_NAME: (
        "Medium bead phase agents that implement directly."
    ),
    LARGE_PHASE_WORKER_MODEL_ALIAS_NAME: (
        "Large bead phase agents that plan before implementation."
    ),
    XLARGE_PHASE_WORKER_MODEL_ALIAS_NAME: (
        "Extra-large bead phase agents that author an epic plan before implementation."
    ),
    SMART_MODEL_ALIAS_NAME: (
        "High-capability model used automatically by large phase agents."
    ),
    SMARTEST_MODEL_ALIAS_NAME: (
        "Highest-capability model used automatically by extra-large phase agents "
        "and large epic landers."
    ),
    CHEAP_MODEL_ALIAS_NAME: (
        "Load-balanced pool used automatically by small phase agents."
    ),
    CHEAPER_MODEL_ALIAS_NAME: (
        "Lower-cost load-balanced pool used automatically by extra-small phase agents."
    ),
    CHEAPEST_MODEL_ALIAS_NAME: (
        "Lowest-cost provider fallback available for explicit use."
    ),
}
