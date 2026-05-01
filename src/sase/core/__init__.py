"""Core utilities — split from the former sase_utils.py module.

This package also hosts the Rust-bindable facade layer (see
``research/202604/rust_backend_migration.md``):

- :mod:`sase.core.rust` — strict ``sase_core_rs`` loader for ported facades.
- :mod:`sase.core.wire` — stable wire records the Rust impl produces/consumes.
- :mod:`sase.core.wire_conversion` — Python ``ChangeSpec`` -> wire records.
- :mod:`sase.core.parser_facade` — :func:`parse_project_file` / ``_bytes``.
- :mod:`sase.core.query_facade` — query parse / build context / evaluate.
- :mod:`sase.core.query_corpus_facade` — persistent Rust query corpus handles.
- :mod:`sase.core.graph_index_facade` — :func:`build_changespec_graph_index`.
- :mod:`sase.core.status_facade` — status transitions + pure status helpers.
- :mod:`sase.core.git_query_facade` — Git query parsers.

The Rust extension is a hard runtime dependency. Ported facades call
:func:`sase.core.rust.require_rust_binding` to look up the relevant
``sase_core_rs`` entry point and raise :class:`ImportError` /
:class:`AttributeError` from a missing or stale wheel rather than silently
falling back to Python. Intentionally unported operations
(per-row query evaluators, graph index construction, side-effecting
status transitions) call their Python implementations directly: they are
host logic, not backend fallbacks.
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
