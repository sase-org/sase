"""Canonical patch import path for commit workflow query helpers."""

from .changespec_queries import *  # noqa: F403
from .changespec_queries import (
    changespec_exists as patch_exists,
    changespec_exists_anywhere as patch_exists_anywhere,
)
