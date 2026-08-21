"""Core utilities — split from the former sase_utils.py module.

This package also hosts the Rust-bindable facade layer (see
``sdd/research/202604/rust_backend_migration.md``):

- :mod:`sase.core.rust` — strict ``sase_core_rs`` loader for ported facades.
- :mod:`sase.core.wire` — stable wire records the Rust impl produces/consumes.
- :mod:`sase.core.wire_conversion` — Python ``Patch`` -> wire records.
- :mod:`sase.core.parser_facade` — :func:`parse_project_file` / :func:`parse_project_bytes`.
- :mod:`sase.core.query_facade` — query parse / build context / evaluate.
- :mod:`sase.core.query_corpus_facade` — persistent Rust query corpus handles.
- :mod:`sase.core.graph_index_facade` — :func:`build_patch_graph_index`.
- :mod:`sase.core.status_facade` — status transitions + pure status helpers.
- :mod:`sase.core.git_query_facade` — Git query parsers.
- :mod:`sase.core.glossary_facade` — glossary validation and matching.

The Rust extension is a hard runtime dependency. Ported facades call
:func:`sase.core.rust.require_rust_binding` to look up the relevant
``sase_core_rs`` entry point and raise :class:`ImportError` /
:class:`AttributeError` from a missing or stale wheel rather than silently
falling back to Python. Intentionally unported operations
(per-row query evaluators, graph index construction, side-effecting
status transitions) call their Python implementations directly: they are
host logic, not backend fallbacks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase._lazy_exports import lazy_dir, lazy_getattr

_LAZY_EXPORTS = {
    # Legacy compatibility aliases retained for older callers.
    "changespec_name_to_branch": (  # legacy compatibility alias
        "sase.core.changespec",  # legacy compatibility module path
        "changespec_name_to_branch",  # legacy compatibility alias
    ),
    "changespec_name_to_branch_with_suffix": (  # legacy compatibility alias
        "sase.core.changespec",  # legacy compatibility module path
        "changespec_name_to_branch_with_suffix",  # legacy compatibility alias
    ),
    "get_workspace_directory_for_changespec": (  # legacy compatibility alias
        "sase.core.changespec",  # legacy compatibility module path
        "get_workspace_directory_for_changespec",  # legacy compatibility alias
    ),
    "get_next_suffix_number": ("sase.core.patch", "get_next_suffix_number"),
    "get_workspace_directory_for_patch": (
        "sase.core.patch",
        "get_workspace_directory_for_patch",
    ),
    "has_suffix": ("sase.core.patch", "has_suffix"),
    "patch_name_to_branch": ("sase.core.patch", "patch_name_to_branch"),
    "patch_name_to_branch_with_suffix": (
        "sase.core.patch",
        "patch_name_to_branch_with_suffix",
    ),
    "patch_names_match": ("sase.core.patch", "patch_names_match"),
    "strip_reverted_suffix": ("sase.core.patch", "strip_reverted_suffix"),
    "copy_to_system_clipboard": (
        "sase.core.clipboard",
        "copy_to_system_clipboard",
    ),
    "GlossaryCatalog": ("sase.core.glossary_facade", "GlossaryCatalog"),
    "GlossaryDiagnostic": (
        "sase.core.glossary_facade",
        "GlossaryDiagnostic",
    ),
    "GlossaryEntry": ("sase.core.glossary_facade", "GlossaryEntry"),
    "GlossaryInputEntry": (
        "sase.core.glossary_facade",
        "GlossaryInputEntry",
    ),
    "GlossarySource": ("sase.core.glossary_facade", "GlossarySource"),
    "GlossarySpan": ("sase.core.glossary_facade", "GlossarySpan"),
    "build_glossary_catalog": (
        "sase.core.glossary_facade",
        "build_glossary_catalog",
    ),
    "compile_glossary_catalog": (
        "sase.core.glossary_facade",
        "compile_glossary_catalog",
    ),
    "lookup_glossary_span": (
        "sase.core.glossary_facade",
        "lookup_glossary_span",
    ),
    "scan_glossary_spans": (
        "sase.core.glossary_facade",
        "scan_glossary_spans",
    ),
    "validate_glossary_entries": (
        "sase.core.glossary_facade",
        "validate_glossary_entries",
    ),
    "ensure_sase_directory": ("sase.core.paths", "ensure_sase_directory"),
    "get_sase_managed_tmpdir": (
        "sase.core.paths",
        "get_sase_managed_tmpdir",
    ),
    "get_sase_directory": ("sase.core.paths", "get_sase_directory"),
    "make_safe_filename": ("sase.core.paths", "make_safe_filename"),
    "shorten_path": ("sase.core.paths", "shorten_path"),
    "get_vendored_tool": ("sase.core.shell", "get_vendored_tool"),
    "run_shell_command": ("sase.core.shell", "run_shell_command"),
    "run_workspace_command": ("sase.core.shell", "run_workspace_command"),
    "strip_hook_prefix": ("sase.core.shell", "strip_hook_prefix"),
    "generate_timestamp": ("sase.core.time", "generate_timestamp"),
    "get_timezone": ("sase.core.time", "get_timezone"),
}


__all__ = [
    "changespec_name_to_branch",  # legacy compatibility alias
    "changespec_name_to_branch_with_suffix",  # legacy compatibility alias
    "copy_to_system_clipboard",
    "ensure_sase_directory",
    "generate_timestamp",
    "GlossaryCatalog",
    "GlossaryDiagnostic",
    "GlossaryEntry",
    "GlossaryInputEntry",
    "GlossarySource",
    "GlossarySpan",
    "get_next_suffix_number",
    "get_sase_managed_tmpdir",
    "get_sase_directory",
    "get_timezone",
    "get_vendored_tool",
    "get_workspace_directory_for_changespec",  # legacy compatibility alias
    "get_workspace_directory_for_patch",
    "has_suffix",
    "make_safe_filename",
    "patch_name_to_branch",
    "patch_name_to_branch_with_suffix",
    "patch_names_match",
    "build_glossary_catalog",
    "compile_glossary_catalog",
    "lookup_glossary_span",
    "run_shell_command",
    "run_workspace_command",
    "scan_glossary_spans",
    "shorten_path",
    "strip_hook_prefix",
    "strip_reverted_suffix",
    "validate_glossary_entries",
]

if TYPE_CHECKING:
    # Legacy compatibility aliases retained for older callers.
    from sase.core.changespec import (
        changespec_name_to_branch,
        changespec_name_to_branch_with_suffix,
        get_workspace_directory_for_changespec,  # legacy compatibility alias
    )
    from sase.core.clipboard import copy_to_system_clipboard
    from sase.core.glossary_facade import (
        GlossaryCatalog,
        GlossaryDiagnostic,
        GlossaryEntry,
        GlossaryInputEntry,
        GlossarySource,
        GlossarySpan,
        build_glossary_catalog,
        compile_glossary_catalog,
        lookup_glossary_span,
        scan_glossary_spans,
        validate_glossary_entries,
    )
    from sase.core.patch import (
        get_next_suffix_number,
        get_workspace_directory_for_patch,
        has_suffix,
        patch_name_to_branch,
        patch_name_to_branch_with_suffix,
        patch_names_match,
        strip_reverted_suffix,
    )
    from sase.core.paths import (
        ensure_sase_directory,
        get_sase_directory,
        get_sase_managed_tmpdir,
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


def __getattr__(name: str) -> object:
    return lazy_getattr(__name__, globals(), _LAZY_EXPORTS, name)


def __dir__() -> list[str]:
    return lazy_dir(globals(), _LAZY_EXPORTS)


# Symvision cannot see Python's package-level lazy hook lookup.
_PACKAGE_GETATTR = __getattr__
_PACKAGE_DIR = __dir__
