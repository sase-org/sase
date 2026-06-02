"""Shared helpers for keymap tests."""

from sase.ace.tui.keymaps import AppKeymaps, load_builtin_app_defaults


def default_app_keymaps(**overrides: str) -> AppKeymaps:
    """Create AppKeymaps from builtin defaults, with optional overrides."""
    kwargs = load_builtin_app_defaults()
    kwargs.update(overrides)
    return AppKeymaps(**kwargs)
