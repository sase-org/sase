"""Legacy aliases for patch grouped navigation actions."""

from typing import Any

from ..patch._grouping_nav import PatchGroupingNavMixin


def _legacy_changespec_targets(targets: Any) -> Any:
    return [
        (
            # legacy compatibility alias
            "changespec" if kind == "patch" else kind,
            payload,
        )  # legacy compatibility alias
        for kind, payload in targets
    ]


class ChangeSpecGroupingNavMixin(PatchGroupingNavMixin):  # legacy compatibility alias
    """Patch grouping navigation with legacy attribute aliases."""

    @property
    def changespecs(self) -> Any:  # legacy compatibility alias
        return getattr(self, "patches", [])

    @changespecs.setter  # legacy compatibility alias
    def changespecs(self, value: Any) -> None:  # legacy compatibility alias
        self.patches = value

    @property
    def _changespec_grouping_mode(self) -> Any:  # legacy compatibility alias
        return getattr(self, "_patch_grouping_mode", None)

    @_changespec_grouping_mode.setter  # legacy compatibility alias
    def _changespec_grouping_mode(
        self, value: Any
    ) -> None:  # legacy compatibility alias
        self._patch_grouping_mode = value

    @property
    def _changespec_group_fold_registry(self) -> Any:  # legacy compatibility alias
        return getattr(self, "_patch_group_fold_registry", None)

    @_changespec_group_fold_registry.setter  # legacy compatibility alias
    def _changespec_group_fold_registry(
        self, value: Any
    ) -> None:  # legacy compatibility alias
        self._patch_group_fold_registry = value

    @property
    def _current_changespec_group_key(self) -> Any:  # legacy compatibility alias
        return getattr(self, "_current_patch_group_key", None)

    @_current_changespec_group_key.setter  # legacy compatibility alias
    def _current_changespec_group_key(
        self, value: Any
    ) -> None:  # legacy compatibility alias
        self._current_patch_group_key = value

    @property
    # legacy compatibility alias
    def _entry_jump_hint_to_changespec_banner(
        self,
    ) -> Any:  # legacy compatibility alias
        return getattr(self, "_entry_jump_hint_to_patch_banner", {})

    @_entry_jump_hint_to_changespec_banner.setter  # legacy compatibility alias
    def _entry_jump_hint_to_changespec_banner(
        self,
        value: Any,
    ) -> None:  # legacy compatibility alias
        self._entry_jump_hint_to_patch_banner = value

    @property
    # legacy compatibility alias
    def _entry_jump_changespec_banner_to_hint(
        self,
    ) -> Any:  # legacy compatibility alias
        return getattr(self, "_entry_jump_patch_banner_to_hint", {})

    @_entry_jump_changespec_banner_to_hint.setter  # legacy compatibility alias
    def _entry_jump_changespec_banner_to_hint(
        self,
        value: Any,
    ) -> None:  # legacy compatibility alias
        self._entry_jump_patch_banner_to_hint = value

    def _changespec_navigation_stops(self) -> Any:  # legacy compatibility alias
        return _legacy_changespec_targets(self._patch_navigation_stops())

    # legacy compatibility alias
    def _navigate_changespec_panel(
        self, direction: int
    ) -> None:  # legacy compatibility alias
        self._navigate_patch_panel(direction)

    def _expand_changespec_group_fold(self) -> bool:  # legacy compatibility alias
        return self._expand_patch_group_fold()

    def _collapse_changespec_group_fold(self) -> bool:  # legacy compatibility alias
        return self._collapse_patch_group_fold()

    def _expand_all_changespec_group_folds(self) -> bool:  # legacy compatibility alias
        return self._expand_all_patch_group_folds()

    # legacy compatibility alias
    def _collapse_all_changespec_group_folds(
        self,
    ) -> bool:  # legacy compatibility alias
        return self._collapse_all_patch_group_folds()

    def _changespec_jump_targets(self) -> Any:  # legacy compatibility alias
        return _legacy_changespec_targets(self._patch_jump_targets())

    # legacy compatibility alias
    def _changespec_banner_focus_still_valid(
        self,
    ) -> bool:  # legacy compatibility alias
        return self._patch_banner_focus_still_valid()


__all__ = ["ChangeSpecGroupingNavMixin"]  # legacy compatibility alias
