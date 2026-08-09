"""Legacy aliases for patch query actions."""

from ..patch._query import PatchQueryMixin

ChangeSpecQueryMixin = PatchQueryMixin

__all__ = ["ChangeSpecQueryMixin"]
