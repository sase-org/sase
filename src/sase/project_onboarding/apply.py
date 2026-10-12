"""Serialized convergent execution of project onboarding plans.

The implementation is split into private modules while this module keeps the
original public import path for :func:`apply_plan`.
"""

from __future__ import annotations

from sase.project_onboarding._apply_entry import apply_plan

__all__ = ["apply_plan"]
