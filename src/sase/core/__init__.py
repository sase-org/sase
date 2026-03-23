"""Core utilities — split from the former sase_utils.py module."""

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
