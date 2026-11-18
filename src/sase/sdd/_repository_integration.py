"""Transactional fetch/rebase integration for SDD repositories.

This module is a facade preserving the original public import path.
Implementation lives in split modules to stay under line limits.
"""

from __future__ import annotations

from sase.sdd._repository_integration_transaction import (
    integrate_sdd_repository_transaction,
)

__all__ = [
    "integrate_sdd_repository_transaction",
]
