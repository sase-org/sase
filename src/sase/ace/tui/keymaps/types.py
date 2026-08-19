"""Keymap configuration types and compatibility exports.

Concrete keymap types, metadata, and key validation live in focused sibling
modules. Imports from this historical module remain supported.
"""

from dataclasses import dataclass, field, fields

from sase.ace.tui.keymaps.app_keymaps import (
    AppKeymaps,
    GateModalKeymaps,
    GlossaryPanelKeymaps,
    MemoryPanelKeymaps,
    ProjectsPaneKeymaps,
    StatisticsPaneKeymaps,
)
from sase.ace.tui.keymaps.key_validation import (
    _CTRL_SPACE_KEY,
    _KEY_ALIASES,
    _KEY_DISPLAY,
    _NAMED_KEYS,
    canonicalize_key_binding,
    canonicalize_single_key,
    is_valid_key,
    normalize_key_binding,
    split_key_alternatives,
)
from sase.ace.tui.keymaps.metadata import (
    _BINDING_META,
    _GATE_BINDING_META,
    _GATE_INPUT_PANEL_BINDING_META,
    _MODE_PREFIX_ACTIONS,
    _STATISTICS_BINDING_META,
)
from sase.ace.tui.keymaps.mode_keymaps import (
    BUILTIN_MODE_NAMES,
    _BUILTIN_MODE_CLASSES,
    BangModeKeymaps,
    BeadIssueModeKeymaps,
    CopyModeKeymaps,
    FoldModeKeymaps,
    LeaderModeKeymaps,
    ModeKeymaps,
)

__all__ = [
    "AppKeymaps",
    "BUILTIN_MODE_NAMES",
    "BangModeKeymaps",
    "BeadIssueModeKeymaps",
    "CopyModeKeymaps",
    "FoldModeKeymaps",
    "GateModalKeymaps",
    "GlossaryPanelKeymaps",
    "KeymapRegistry",
    "LeaderModeKeymaps",
    "MemoryPanelKeymaps",
    "ModeKeymaps",
    "ProjectsPaneKeymaps",
    "StatisticsPaneKeymaps",
    "_BINDING_META",
    "_BUILTIN_MODE_CLASSES",
    "_CTRL_SPACE_KEY",
    "_GATE_BINDING_META",
    "_GATE_INPUT_PANEL_BINDING_META",
    "_KEY_ALIASES",
    "_KEY_DISPLAY",
    "_MODE_PREFIX_ACTIONS",
    "_NAMED_KEYS",
    "_STATISTICS_BINDING_META",
    "canonicalize_key_binding",
    "canonicalize_single_key",
    "is_valid_key",
    "normalize_key_binding",
    "split_key_alternatives",
]


# Every AppKeymaps field must have a _BINDING_META entry and vice versa.
_BINDING_META_ACTIONS: frozenset[str] = frozenset(a for a, _, _ in _BINDING_META)
_APP_KEYMAP_FIELDS: frozenset[str] = frozenset(f.name for f in fields(AppKeymaps))

if _BINDING_META_ACTIONS != _APP_KEYMAP_FIELDS:
    _only_in_meta = sorted(_BINDING_META_ACTIONS - _APP_KEYMAP_FIELDS)
    _only_in_keymaps = sorted(_APP_KEYMAP_FIELDS - _BINDING_META_ACTIONS)
    _parts: list[str] = []
    if _only_in_meta:
        _parts.append(f"in _BINDING_META but not AppKeymaps: {_only_in_meta}")
    if _only_in_keymaps:
        _parts.append(f"in AppKeymaps but not _BINDING_META: {_only_in_keymaps}")
    raise RuntimeError(f"_BINDING_META / AppKeymaps mismatch — {'; '.join(_parts)}")


@dataclass
class KeymapRegistry:
    """Top-level container for all keymap configuration."""

    app: AppKeymaps
    statistics: StatisticsPaneKeymaps = field(default_factory=StatisticsPaneKeymaps)
    gate: GateModalKeymaps = field(default_factory=GateModalKeymaps)
    glossary: GlossaryPanelKeymaps = field(default_factory=GlossaryPanelKeymaps)
    memory: MemoryPanelKeymaps = field(default_factory=MemoryPanelKeymaps)
    projects: ProjectsPaneKeymaps = field(default_factory=ProjectsPaneKeymaps)
    modes: dict[str, ModeKeymaps] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Ensure built-in modes exist with defaults if not provided.
        for name, cls in _BUILTIN_MODE_CLASSES.items():
            if name not in self.modes:
                self.modes[name] = cls()

    @property
    def fold_mode(self) -> FoldModeKeymaps:
        mode = self.modes["fold_mode"]
        assert isinstance(mode, FoldModeKeymaps)
        return mode

    @property
    def copy_mode(self) -> CopyModeKeymaps:
        mode = self.modes["copy_mode"]
        assert isinstance(mode, CopyModeKeymaps)
        return mode

    @property
    def leader_mode(self) -> LeaderModeKeymaps:
        mode = self.modes["leader_mode"]
        assert isinstance(mode, LeaderModeKeymaps)
        return mode

    @property
    def bang_mode(self) -> BangModeKeymaps:
        mode = self.modes["bang_mode"]
        assert isinstance(mode, BangModeKeymaps)
        return mode

    @property
    def bead_issue_mode(self) -> BeadIssueModeKeymaps:
        mode = self.modes["bead_issue_mode"]
        assert isinstance(mode, BeadIssueModeKeymaps)
        return mode
