"""Legacy aliases for the patch action mixins."""

from ..patch import (
    PatchDisplayMixin,
    PatchLoadingMixin,
    PatchMixin,
    PatchQueryMixin,
)
from ._grouping_nav import ChangeSpecGroupingNavMixin
from ._onboarding import ChangeSpecOnboardingMixin

ChangeSpecDisplayMixin = PatchDisplayMixin
ChangeSpecLoadingMixin = PatchLoadingMixin
ChangeSpecMixin = PatchMixin
ChangeSpecQueryMixin = PatchQueryMixin

__all__ = [
    "ChangeSpecDisplayMixin",
    "ChangeSpecGroupingNavMixin",
    "ChangeSpecLoadingMixin",
    "ChangeSpecMixin",
    "ChangeSpecOnboardingMixin",
    "ChangeSpecQueryMixin",
]
