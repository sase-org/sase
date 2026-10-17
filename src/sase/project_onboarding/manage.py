"""Recoverable commit-and-push of a repository's SASE management marker.

The implementation lives in the sibling ``_manage_*`` modules. This module
keeps the original public import path for :func:`manage_repository` and
:class:`ManagementError`.
"""

from __future__ import annotations

from sase.project_onboarding._manage_origin import manage_repository
from sase.project_onboarding.manage_git import ManagementError

__all__ = ["ManagementError", "manage_repository"]
