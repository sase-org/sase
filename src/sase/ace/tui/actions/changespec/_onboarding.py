"""Legacy aliases for patch onboarding actions."""

from typing import Any

from ..patch._onboarding import PatchOnboardingMixin


class ChangeSpecOnboardingMixin(PatchOnboardingMixin):
    """Patch onboarding with legacy attribute aliases."""

    @property
    def changespecs(self) -> Any:
        return getattr(self, "patches", [])

    @changespecs.setter
    def changespecs(self, value: Any) -> None:
        self.patches = value

    @property
    def _all_changespecs(self) -> Any:
        return getattr(self, "_all_patches", [])

    @_all_changespecs.setter
    def _all_changespecs(self, value: Any) -> None:
        self._all_patches = value

    @property
    def _changespecs_first_load_done(self) -> bool:
        return getattr(self, "_patches_first_load_done", False)

    @_changespecs_first_load_done.setter
    def _changespecs_first_load_done(self, value: bool) -> None:
        self._patches_first_load_done = value

    def _should_show_changespecs_onboarding(self) -> bool:
        return self._should_show_patches_onboarding()

    def _sync_changespecs_onboarding(self) -> bool:
        return self._sync_patches_onboarding()

    @staticmethod
    def _set_changespecs_onboarding_layout(view: object, active: bool) -> None:
        PatchOnboardingMixin._set_patches_onboarding_layout(view, active)


__all__ = ["ChangeSpecOnboardingMixin"]
