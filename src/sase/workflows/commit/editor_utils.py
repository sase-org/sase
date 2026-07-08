"""Editor utilities for commit message editing."""

from sase.editor_resolver import resolve_editor


def get_editor() -> str:
    """Get the editor to use for commit messages.

    Returns:
        The editor command to use. Checks $VISUAL/$EDITOR first, then falls
        back to nvim if available, otherwise vim.
    """
    return resolve_editor().command_string


def get_editor_argv() -> tuple[str, ...]:
    """Return the editor command as argv."""
    return resolve_editor().argv
