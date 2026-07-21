"""Shared helpers for ``sase doctor`` configuration checks."""

from __future__ import annotations

MAX_DETAIL_ROWS = 10

#: Implicit aliases retired by the model-alias migration (epic sase-5d), mapped
#: to the guidance doctor surfaces for each. ``worker``/``other`` no longer
#: resolve as implicit aliases (the worker lane was retired in phase 4); they are
#: no longer documented, completed, or shipped, so configs referencing them
#: should migrate.
REMOVED_IMPLICIT_ALIAS_GUIDANCE: dict[str, str] = {
    "worker": "use a role alias such as @coder or an explicit model",
    "other": "use @default or an explicit provider/model",
    "phase_worker": (
        "use @medium_phase_worker for medium phase work, @default for the "
        "former fallback behavior, or define phase_worker as a custom alias"
    ),
}
