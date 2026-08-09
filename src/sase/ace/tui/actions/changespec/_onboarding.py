"""Legacy aliases for patch onboarding actions."""

from typing import Any

from ..patch._onboarding import PatchOnboardingMixin


class ChangeSpecOnboardingMixin(PatchOnboardingMixin):  # legacy compatibility alias
    """Patch onboarding with legacy attribute aliases."""

    @property
    def changespecs(self) -> Any:  # legacy compatibility alias
        return getattr(self, "patches", [])

    @changespecs.setter  # legacy compatibility alias
    def changespecs(self, value: Any) -> None:  # legacy compatibility alias
        self.patches = value

    @property
    def _all_changespecs(self) -> Any:  # legacy compatibility alias
        return getattr(self, "_all_patches", [])

    @_all_changespecs.setter  # legacy compatibility alias
    def _all_changespecs(self, value: Any) -> None:  # legacy compatibility alias
        self._all_patches = value

    @property
    def _changespecs_first_load_done(self) -> bool:  # legacy compatibility alias
        return getattr(self, "_patches_first_load_done", False)

    @_changespecs_first_load_done.setter  # legacy compatibility alias
    def _changespecs_first_load_done(
        self, value: bool
    ) -> None:  # legacy compatibility alias
        self._patches_first_load_done = value

    def _should_show_changespecs_onboarding(self) -> bool:  # legacy compatibility alias
        return self._should_show_patches_onboarding()

    def _sync_changespecs_onboarding(self) -> bool:  # legacy compatibility alias
        return self._sync_patches_onboarding()

    @staticmethod
    # legacy compatibility alias
    def _set_changespecs_onboarding_layout(
        view: object, active: bool
    ) -> None:  # legacy compatibility alias
        PatchOnboardingMixin._set_patches_onboarding_layout(view, active)


__all__ = ["ChangeSpecOnboardingMixin"]  # legacy compatibility alias
