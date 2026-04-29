"""Core utilities — split from the former sase_utils.py module.

This package also hosts the Phase 0 facade for the future Rust backend (see
``research/202604/rust_backend_migration.md``):

- :mod:`sase.core.backend` — ``SASE_CORE_BACKEND`` selection + dispatch.
- :mod:`sase.core.dual_run` — ``SASE_CORE_DUAL_RUN`` JSONL comparison logging.
- :mod:`sase.core.wire` — stable wire records a Rust impl will produce/consume.
- :mod:`sase.core.wire_conversion` — Python ``ChangeSpec`` -> wire records.
- :mod:`sase.core.parser_facade` — :func:`parse_project_file` / ``_bytes``.
- :mod:`sase.core.query_facade` — query parse / build context / evaluate.
- :mod:`sase.core.graph_index_facade` — :func:`build_changespec_graph_index`.
- :mod:`sase.core.status_facade` — status transitions + pure status helpers.

Phase 0A ships only the Python implementation; ``SASE_CORE_BACKEND=rust``
intentionally raises :class:`sase.core.backend.RustBackendUnavailableError`.
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
