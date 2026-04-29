"""Core utilities — split from the former sase_utils.py module.

This package also hosts the facade for the optional Rust backend (see
``research/202604/rust_backend_migration.md`` and
``plans/202604/rust_backend_phase0.md``):

- :mod:`sase.core.backend` — ``SASE_CORE_BACKEND`` selection + dispatch.
- :mod:`sase.core.dual_run` — ``SASE_CORE_DUAL_RUN`` JSONL comparison logging.
- :mod:`sase.core.wire` — stable wire records a Rust impl will produce/consume.
- :mod:`sase.core.wire_conversion` — Python ``ChangeSpec`` -> wire records.
- :mod:`sase.core.parser_facade` — :func:`parse_project_file` / ``_bytes``.
- :mod:`sase.core.query_facade` — query parse / build context / evaluate.
- :mod:`sase.core.graph_index_facade` — :func:`build_changespec_graph_index`.
- :mod:`sase.core.status_facade` — status transitions + pure status helpers.
- :mod:`sase.core.git_query_facade` — Git query parsers (Phase 5B; pure
  string-in / primitive-out, Python-only until Phase 5D wires Rust dispatch).

The backend boundary
--------------------
Each facade module exposes a small set of public functions that delegate to
:func:`sase.core.backend.dispatch`. Dispatch picks the active backend
(``rust`` by default starting in Phase 6F; ``python`` is the documented
escape hatch) and, when ``SASE_CORE_DUAL_RUN=1`` is set, runs both
implementations to log a comparison record. The Python result is always
what callers receive under dual-run, so enabling it cannot drift TUI/CLI
behavior.

Why a Python escape hatch still exists
--------------------------------------
The pure-Python implementations remain through Phase 7 so a patch release
can restore the old default if a packaging or parity regression appears in
the field. The dispatcher is the only place backend selection happens, and
shipped Rust operations fail loudly
(:class:`sase.core.backend.RustBackendUnavailableError`) when their expected
binding is missing — default Rust does not silently fall back to Python.
APIs that are intentionally unported opt into an explicit Python fallback
under Rust mode so the default backend means "use Rust where shipped,
Python where not yet ported."
"""

from sase.core.changespec import (
    changespec_name_to_branch,
    changespec_name_to_branch_with_suffix,
    get_next_suffix_number,
    get_workspace_directory_for_changespec,
    has_suffix,
    strip_reverted_suffix,
)
from sase.core.paths import (
    ensure_sase_directory,
    get_sase_directory,
    get_sase_tmpdir,
    make_safe_filename,
    shorten_path,
)
from sase.core.shell import (
    get_vendored_tool,
    run_shell_command,
    run_workspace_command,
    strip_hook_prefix,
)
from sase.core.time import generate_timestamp, get_timezone

__all__ = [
    "changespec_name_to_branch",
    "changespec_name_to_branch_with_suffix",
    "ensure_sase_directory",
    "generate_timestamp",
    "get_next_suffix_number",
    "get_sase_directory",
    "get_sase_tmpdir",
    "get_timezone",
    "get_vendored_tool",
    "get_workspace_directory_for_changespec",
    "has_suffix",
    "make_safe_filename",
    "run_shell_command",
    "run_workspace_command",
    "shorten_path",
    "strip_hook_prefix",
    "strip_reverted_suffix",
]
