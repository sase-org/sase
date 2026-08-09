"""Legacy aliases for patch grouped navigation actions."""

from typing import Any

from ..patch._grouping_nav import PatchGroupingNavMixin


def _legacy_changespec_targets(targets: Any) -> Any:
    return [
        ("changespec" if kind == "patch" else kind, payload)
        for kind, payload in targets
    ]


class ChangeSpecGroupingNavMixin(PatchGroupingNavMixin):
    """Patch grouping navigation with legacy attribute aliases."""

    @property
    def changespecs(self) -> Any:
        return getattr(self, "patches", [])

    @changespecs.setter
    def changespecs(self, value: Any) -> None:
        self.patches = value

    @property
    def _changespec_grouping_mode(self) -> Any:
        return getattr(self, "_patch_grouping_mode", None)

    @_changespec_grouping_mode.setter
    def _changespec_grouping_mode(self, value: Any) -> None:
        self._patch_grouping_mode = value

    @property
    def _changespec_group_fold_registry(self) -> Any:
        return getattr(self, "_patch_group_fold_registry", None)

    @_changespec_group_fold_registry.setter
    def _changespec_group_fold_registry(self, value: Any) -> None:
        self._patch_group_fold_registry = value

    @property
    def _current_changespec_group_key(self) -> Any:
        return getattr(self, "_current_patch_group_key", None)

    @_current_changespec_group_key.setter
    def _current_changespec_group_key(self, value: Any) -> None:
        self._current_patch_group_key = value

    def _changespec_navigation_stops(self) -> Any:
        return _legacy_changespec_targets(self._patch_navigation_stops())

    def _navigate_changespec_panel(self, direction: int) -> None:
        self._navigate_patch_panel(direction)

    def _expand_changespec_group_fold(self) -> bool:
        return self._expand_patch_group_fold()

    def _collapse_changespec_group_fold(self) -> bool:
        return self._collapse_patch_group_fold()

    def _expand_all_changespec_group_folds(self) -> bool:
        return self._expand_all_patch_group_folds()

    def _collapse_all_changespec_group_folds(self) -> bool:
        return self._collapse_all_patch_group_folds()

    def _changespec_jump_targets(self) -> Any:
        return _legacy_changespec_targets(self._patch_jump_targets())

    def _changespec_banner_focus_still_valid(self) -> bool:
        return self._patch_banner_focus_still_valid()


__all__ = ["ChangeSpecGroupingNavMixin"]
