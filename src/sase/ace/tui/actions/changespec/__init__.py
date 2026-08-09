"""Legacy aliases for the patch action mixins."""

from ..patch import (
    PatchDisplayMixin,
    PatchLoadingMixin,
    PatchMixin,
    PatchQueryMixin,
)
from ._grouping_nav import ChangeSpecGroupingNavMixin  # legacy compatibility alias
from ._onboarding import ChangeSpecOnboardingMixin  # legacy compatibility alias

ChangeSpecDisplayMixin = PatchDisplayMixin  # legacy compatibility alias
ChangeSpecLoadingMixin = PatchLoadingMixin  # legacy compatibility alias
ChangeSpecMixin = PatchMixin  # legacy compatibility alias
ChangeSpecQueryMixin = PatchQueryMixin  # legacy compatibility alias

__all__ = [
    "ChangeSpecDisplayMixin",  # legacy compatibility alias
    "ChangeSpecGroupingNavMixin",  # legacy compatibility alias
    "ChangeSpecLoadingMixin",  # legacy compatibility alias
    "ChangeSpecMixin",  # legacy compatibility alias
    "ChangeSpecOnboardingMixin",  # legacy compatibility alias
    "ChangeSpecQueryMixin",  # legacy compatibility alias
]
