"""Legacy aliases for patch loading actions."""

from ..patch._loading import PatchLoadingMixin

ChangeSpecLoadingMixin = PatchLoadingMixin  # legacy compatibility alias

__all__ = ["ChangeSpecLoadingMixin"]  # legacy compatibility alias
