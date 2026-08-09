"""Legacy aliases for patch query actions."""

from ..patch._query import PatchQueryMixin

ChangeSpecQueryMixin = PatchQueryMixin  # legacy compatibility alias

__all__ = ["ChangeSpecQueryMixin"]  # legacy compatibility alias
