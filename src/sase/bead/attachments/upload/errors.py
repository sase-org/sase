"""Error types for attachment placement and upload."""

from __future__ import annotations


class AttachmentTooLargeError(ValueError):
    """An attachment exceeds the git tier and ``-L`` was not accepted."""


class AttachmentStoreMissingError(ValueError):
    """``require_upload`` needs a shared store but none exists."""


__all__ = [
    "AttachmentStoreMissingError",
    "AttachmentTooLargeError",
]
