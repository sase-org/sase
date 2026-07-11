"""Shared SDD file-operation types."""

from pathlib import Path
from typing import Literal, NamedTuple


class SddExpectedTextFile(NamedTuple):
    path: Path
    content: str


class SddExpectedBytesFile(NamedTuple):
    path: Path
    content: bytes


SddInitOperation = Literal["create", "update"]


class SddInitAction(NamedTuple):
    """One generated SDD file that is missing or stale."""

    path: Path
    operation: SddInitOperation
    detail: str
    new_content: str | bytes | None = None
