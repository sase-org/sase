"""Failure types raised while fetching the SASE plugin catalog from GitHub.

These live in their own module so the ``gh`` boundary, the JSON parser, and the
fetch driver can all raise from a shared hierarchy without importing each other.
"""

from __future__ import annotations

#: Hint reused (almost) verbatim from ``sase doctor``'s GitHub plugin check.
GH_INSTALL_HINT = (
    "Install the GitHub CLI and run `gh auth login`, then retry. "
    "See https://cli.github.com/."
)


class PluginCatalogError(Exception):
    """Base class for catalog-fetch failures."""


class GhNotFoundError(PluginCatalogError):
    """The ``gh`` CLI is not available on ``PATH``."""

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message or f"the GitHub CLI (gh) was not found on PATH. {GH_INSTALL_HINT}"
        )


class GhCommandError(PluginCatalogError):
    """The ``gh`` CLI ran but failed (non-zero, timeout, or OS error)."""


class CatalogParseError(PluginCatalogError):
    """The ``gh`` output could not be parsed into catalog entries."""
