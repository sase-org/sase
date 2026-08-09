"""Legacy aliases for patch core actions."""

from ..patch._core import PatchMixin

ChangeSpecMixin = PatchMixin  # legacy compatibility alias

__all__ = ["ChangeSpecMixin"]  # legacy compatibility alias
