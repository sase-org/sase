"""Shared helpers for ``sase doctor`` configuration checks."""

from __future__ import annotations

MAX_DETAIL_ROWS = 10

#: Implicit aliases retired by model-alias migrations, mapped to the guidance
#: doctor surfaces for each. ``worker``/``other`` are from the earlier role
#: migration; the remaining names were retired by the compact five-size-alias
#: contract.
REMOVED_IMPLICIT_ALIAS_GUIDANCE: dict[str, str] = {
    "worker": (
        "the retired @worker alias no longer resolves; use a size alias such "
        "as @medium, or an explicit model"
    ),
    "other": "use @large or an explicit provider/model",
    "coder": (
        "accepted tale follow-ups now route by tale size; use a size alias "
        "such as @medium or an explicit model"
    ),
    "phase_worker": (
        "use @medium for medium phase work, @large for the "
        "former fallback behavior, or define phase_worker as a custom alias"
    ),
    "xsmall_phase_worker": "use @xsmall instead",
    "small_phase_worker": "use @small instead",
    "medium_phase_worker": "use @medium instead",
    "large_phase_worker": "use @large instead",
    "xlarge_phase_worker": "use @xlarge instead",
    "default": "move this launch-default target to llm_provider.default_model",
    "epic_lander": "move this target to llm_provider.epic_lander_model",
    "big_epic_lander": "move this target to llm_provider.big_epic_lander_model",
    "xsmall_worker": "use @xsmall instead",
    "small_worker": "use @small instead",
    "medium_worker": "use @medium instead",
    "large_worker": "use @large instead",
    "xlarge_worker": "use @xlarge instead",
    "cheaper": (
        "use @xsmall, or define a custom @cheaper alias to preserve a customized target"
    ),
    "cheap": (
        "use @small, or define a custom @cheap alias to preserve a customized target"
    ),
    "smart": (
        "use @medium, or define a custom @smart alias to preserve a customized target"
    ),
    "smarter": (
        "use @large, or define a custom @smarter alias to preserve a customized target"
    ),
    "smartest": (
        "use @xlarge, or define a custom @smartest alias to preserve a "
        "customized target"
    ),
    "cheapest": (
        "define a described custom @cheapest alias if you still need this target"
    ),
}
