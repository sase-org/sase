"""Canonical handler facade for the ``sase patch`` command group."""

from sase.main.changespec_handler import handle_changespec_command, handle_patch_command

__all__ = ["handle_changespec_command", "handle_patch_command"]
