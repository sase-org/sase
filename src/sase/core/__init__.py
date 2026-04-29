"""Core utilities — split from the former sase_utils.py module.

This package also hosts the Phase 0 facade for the future Rust backend (see
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
backend selection happens, and a missing Rust extension fails loudly
(:class:`sase.core.backend.RustBackendUnavailableError`) instead of silently
falling back. Phase 1 will add an optional ``sase_core_rs`` PyO3 extension
that registers itself as the ``rust_impl`` argument for one operation at a
time, starting with :func:`parse_project_bytes`. Consumers of the facade do
not need to change when that happens.

Phase 0 status: only the Python implementation ships;
``SASE_CORE_BACKEND=rust`` intentionally raises
:class:`sase.core.backend.RustBackendUnavailableError`.
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
