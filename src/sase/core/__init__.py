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
(``python`` by default, ``rust`` when explicitly requested) and, when
``SASE_CORE_DUAL_RUN=1`` is set, runs both implementations to log a
comparison record. The Python result is always what callers receive, so
enabling dual-run cannot drift TUI/CLI behavior.

Why Rust is optional
--------------------
A Rust implementation never has to exist for sase to work; that is the point
of Phase 0. The default backend is Python, the dispatcher is the only place
backend selection happens, and shipped Rust operations fail loudly
(:class:`sase.core.backend.RustBackendUnavailableError`) when their expected
binding is missing. APIs that are intentionally unported can opt into an
explicit Python fallback under ``SASE_CORE_BACKEND=rust`` so selecting the Rust
backend means "use Rust where shipped, Python where not yet ported."
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
