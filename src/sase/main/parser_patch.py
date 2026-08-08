"""Canonical parser registrar for the ``sase patch`` command group."""

from sase.main.parser_changespec import (
    register_changespec_parser,
    register_patch_parser,
)

__all__ = ["register_changespec_parser", "register_patch_parser"]
