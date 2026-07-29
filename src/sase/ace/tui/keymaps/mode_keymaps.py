"""Dataclasses for prefix-key modes."""

from dataclasses import dataclass, field


@dataclass
class ModeKeymaps:
    """Generic container for a prefix-key mode."""

    prefix: str = ""
    keys: dict[str, str | dict[str, str]] = field(default_factory=dict)


@dataclass
class FoldModeKeymaps(ModeKeymaps):
    """Typed fields for the built-in fold mode."""

    prefix: str = "z"
    keys: dict[str, str | dict[str, str]] = field(
        default_factory=lambda: {
            "cycle_commits": "c",
            "cycle_hooks": "h",
            "cycle_mentors": "m",
            "cycle_timestamps": "t",
            "cycle_deltas": "d",
            "toggle_commits": "C",
            "toggle_hooks": "H",
            "toggle_mentors": "M",
            "toggle_timestamps": "T",
            "toggle_deltas": "D",
            "cycle_all": "z",
            "toggle_all": "Z",
            "set_level_1": "1",
            "set_level_2": "2",
            "set_level_3": "3",
            "agents": {
                "cycle_level": "z",
                "toggle_all": "Z",
                "cycle_section": "a",
                "toggle_section": "A",
                "set_level_1": "1",
                "set_level_2": "2",
                "set_level_3": "3",
                "set_level_4": "4",
            },
        }
    )


@dataclass
class CopyModeKeymaps(ModeKeymaps):
    """Typed fields for the built-in copy mode (nested per-tab keys)."""

    prefix: str = "percent_sign"
    keys: dict[str, str | dict[str, str]] = field(
        default_factory=lambda: {
            "changespecs": {
                "raw": "percent_sign",
                "with_snapshot": "exclamation_mark",
                "bug": "b",
                "pr_number": "c",
                "name": "n",
                "spec": "p",
                "snapshot": "s",
            },
            "artifacts_commits": {
                "sha": "percent_sign",
                "reference": "at",
                "handoff": "exclamation_mark",
                "message": "m",
                "repo_sha": "r",
                "plan": "p",
                "snapshot": "s",
            },
            "artifacts_plans": {
                "reference": "at",
                "handoff": "exclamation_mark",
                "path": "p",
                "title": "t",
                "body": "b",
                "snapshot": "s",
            },
            "artifacts_chats": {
                "reference": "at",
                "handoff": "exclamation_mark",
                "path": "p",
                "agent": "a",
                "transcript": "t",
                "snapshot": "s",
            },
            "artifacts_bugs": {
                "reference": "at",
                "handoff": "exclamation_mark",
                "number": "b",
                "url": "u",
                "title": "t",
                "prompt": "p",
                "snapshot": "s",
            },
            "agents": {
                "chat": "c",
                "file_path": "E",
                "name": "n",
                "prompt": "p",
                "snapshot": "s",
            },
            "axe": {
                "visible": "o",
                "full": "O",
                "snapshot": "s",
            },
        }
    )


@dataclass
class LeaderModeKeymaps(ModeKeymaps):
    """Typed fields for the built-in leader mode."""

    prefix: str = "comma"
    keys: dict[str, str | dict[str, str]] = field(
        default_factory=lambda: {
            "repeat_last": "comma",
            "edit_query": "slash",
            "show_help": "question_mark",
            "run_cmd": "exclamation_mark",
            "runners": "R",
            "revert_agent": "r",
            "kill_mentors": "M",
            "review_mentors": "C",
            "agent_home": "h",
            "agent_from_cl": "space",
            "toggle_agent_panel_grouping": "g",
            "jump_to_next_unread_done_agent": "j",
            "jump_to_next_stopped_agent": "J",
            "full_history_refresh": "y",
            "mark_all_unread_done_agents_read": "u",
            "kill_and_edit": "x",
            "clear_comments": "c",
            "open_prompt_stash": "at",
            "prompt_history": "full_stop",
            "prompt_history_edit_first": "ctrl+g",
            "prompt_history_cancelled": "greater_than_sign",
            "agent_run_log": "A",
            "models_panel": "m",
            "update_sase": "U",
            "capture_agents_repro": "B",
            "toggle_agents_repro_checks": "T",
            "jump_to_notification": "n",
        }
    )


@dataclass
class BangModeKeymaps(ModeKeymaps):
    """Typed fields for the built-in bang mode."""

    prefix: str = "exclamation_mark"
    keys: dict[str, str | dict[str, str]] = field(
        default_factory=lambda: {
            "run_cmd": "exclamation_mark",
            "toggle_axe": "x",
        }
    )


# Map of built-in mode names to their typed dataclass constructors.
_BUILTIN_MODE_CLASSES: dict[str, type[ModeKeymaps]] = {
    "fold_mode": FoldModeKeymaps,
    "copy_mode": CopyModeKeymaps,
    "leader_mode": LeaderModeKeymaps,
    "bang_mode": BangModeKeymaps,
}

BUILTIN_MODE_NAMES: frozenset[str] = frozenset(_BUILTIN_MODE_CLASSES)
