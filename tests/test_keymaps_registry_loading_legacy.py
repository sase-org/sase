"""Tests for retired, stale, and legacy keymap registry loading."""

import logging

import pytest

from sase.ace.tui.keymaps import load_keymap_registry


def test_retired_selected_panel_toggle_leader_override_is_filtered() -> None:
    reg = load_keymap_registry(
        {
            "keymaps": {
                "modes": {
                    "leader_mode": {"keys": {"toggle_selected_agent_panels": "P"}}
                }
            }
        }
    )

    assert "toggle_selected_agent_panels" not in reg.leader_mode.keys


def test_app_query_and_help_overrides_are_honored_while_leader_help_is_retired(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG, logger="sase.ace.tui.keymaps.registry"):
        reg = load_keymap_registry(
            {
                "keymaps": {
                    "app": {"edit_query": "f5", "show_help": "f6"},
                    "modes": {"leader_mode": {"keys": {"show_help": "f7"}}},
                }
            }
        )

    assert reg.app.edit_query == "f5"
    assert reg.app.show_help == "f6"
    assert "show_help" not in reg.leader_mode.keys
    assert "Ignoring retired app keymap action: edit_query" not in caplog.text
    assert "Ignoring retired app keymap action: show_help" not in caplog.text
    assert "Unknown keymap action" not in caplog.text


def test_retired_plans_bead_action_overrides_are_dropped() -> None:
    reg = load_keymap_registry(
        {"keymaps": {"app": {"plans_expand": "f6", "plans_open_bug": "f7"}}}
    )

    assert not hasattr(reg.app, "plans_expand")
    assert not hasattr(reg.app, "plans_open_bug")


def test_retired_bugs_subtab_action_overrides_are_dropped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG, logger="sase.ace.tui.keymaps.registry"):
        reg = load_keymap_registry(
            {"keymaps": {"app": {"next_bug": "j", "activate_bug_link": "f8"}}}
        )

    assert not hasattr(reg.app, "next_bug")
    assert not hasattr(reg.app, "activate_bug_link")
    assert "Unknown keymap action" not in caplog.text


def test_retired_activate_control_override_aliases_submit_primary(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        reg = load_keymap_registry({"keymaps": {"gate": {"activate_control": "f12"}}})

    assert reg.gate.submit_primary == "f12"
    assert "deprecated" in caplog.text


def test_legacy_commits_action_override_migrates_to_stitches(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        reg = load_keymap_registry({"keymaps": {"app": {"commits_next": "P"}}})
    assert reg.app.stitches_next == "P"
    assert "deprecated" in caplog.text


def test_stitches_action_override_wins_over_legacy_commits_alias(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        reg = load_keymap_registry(
            {
                "keymaps": {
                    "app": {"commits_next": "B", "stitches_next": "f24"},
                }
            }
        )
    assert reg.app.stitches_next == "f24"
    assert "deprecated" in caplog.text
    assert "ignored" in caplog.text


def test_legacy_agents_reverse_cycle_override_migrates_to_toggle_all(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        reg = load_keymap_registry(
            {
                "keymaps": {
                    "modes": {
                        "fold_mode": {
                            "keys": {
                                "agents": {
                                    "cycle_level_back": "v",
                                    "toggle_all": "Z",
                                }
                            }
                        }
                    }
                }
            }
        )

    agent_keys = reg.fold_mode.keys["agents"]
    assert isinstance(agent_keys, dict)
    assert agent_keys["toggle_all"] == "v"
    assert "cycle_level_back" not in agent_keys
    assert "deprecated" in caplog.text


def test_agents_toggle_all_override_wins_over_legacy_alias() -> None:
    reg = load_keymap_registry(
        {
            "keymaps": {
                "modes": {
                    "fold_mode": {
                        "keys": {
                            "agents": {
                                "cycle_level_back": "v",
                                "toggle_all": "x",
                            }
                        }
                    }
                }
            }
        }
    )

    agent_keys = reg.fold_mode.keys["agents"]
    assert isinstance(agent_keys, dict)
    assert agent_keys["toggle_all"] == "x"
    assert "cycle_level_back" not in agent_keys


def test_stale_kill_marked_and_edit_override_is_dropped() -> None:
    """A lingering ``kill_marked_and_edit`` override cannot revive the key.

    The action was folded into the contextual ``kill_and_edit`` (``,x``); a
    stale user config entry must be filtered during load so the deep-merge
    does not reintroduce it, while other leader overrides still apply.
    """
    reg = load_keymap_registry(
        {
            "keymaps": {
                "modes": {
                    "leader_mode": {
                        "keys": {
                            "kill_marked_and_edit": "X",
                            "kill_and_edit": "y",
                        },
                    },
                },
            },
        }
    )
    assert "kill_marked_and_edit" not in reg.leader_mode.keys
    assert reg.leader_mode.keys["kill_and_edit"] == "y"  # legit override survives


def test_stale_kill_marked_and_edit_override_does_not_collide_with_kill_and_edit_last() -> (
    None
):
    """A stale ``kill_marked_and_edit`` override cannot shadow the new ``,X`` default.

    ``kill_marked_and_edit`` used to bind ``X`` before it was folded into
    contextual ``,x``; ``X`` is now the live default for the unrelated
    ``kill_and_edit_last`` action. The retired-key filter must still drop the
    stale override so it cannot reintroduce a competing binding on ``X``.
    """
    reg = load_keymap_registry(
        {
            "keymaps": {
                "modes": {
                    "leader_mode": {
                        "keys": {
                            "kill_marked_and_edit": "X",
                        },
                    },
                },
            },
        }
    )
    assert "kill_marked_and_edit" not in reg.leader_mode.keys
    assert reg.leader_mode.keys["kill_and_edit_last"] == "X"


def test_user_override_binding_another_action_to_shift_x_round_trips() -> None:
    """A legitimate user override of an unrelated action onto ``X`` still applies.

    This does not collide with ``kill_and_edit_last``'s own default ``X``
    binding: a user config is free to move ``kill_and_edit_last`` off ``X``
    while binding another action onto it.
    """
    reg = load_keymap_registry(
        {
            "keymaps": {
                "modes": {
                    "leader_mode": {
                        "keys": {
                            "kill_and_edit_last": "z",
                            "full_history_refresh": "X",
                        },
                    },
                },
            },
        }
    )
    assert reg.leader_mode.keys["kill_and_edit_last"] == "z"
    assert reg.leader_mode.keys["full_history_refresh"] == "X"


def test_stale_restore_prompt_stash_override_is_dropped() -> None:
    """A lingering ``restore_prompt_stash`` override cannot revive global ``,P``.

    The global leader restore was retired in favour of ``@`` and the
    prompt-local ``Ctrl+G p`` panel opener; a stale user config entry must be
    filtered during load so the deep-merge does not reintroduce it, while other
    leader overrides still apply.
    """
    reg = load_keymap_registry(
        {
            "keymaps": {
                "modes": {
                    "leader_mode": {
                        "keys": {
                            "restore_prompt_stash": "P",
                            "kill_and_edit": "y",
                        },
                    },
                },
            },
        }
    )
    assert "restore_prompt_stash" not in reg.leader_mode.keys
    assert reg.leader_mode.keys["kill_and_edit"] == "y"  # legit override survives


def test_legacy_artifacts_commits_copy_group_migrates_to_stitches(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        reg = load_keymap_registry(
            {
                "keymaps": {
                    "modes": {
                        "copy_mode": {
                            "keys": {
                                "artifacts_commits": {"sha": "S"},  # legacy wire key
                            },
                        },
                    },
                },
            }
        )
    stitches_keys = reg.copy_mode.keys["artifacts_stitches"]
    assert isinstance(stitches_keys, dict)
    assert stitches_keys["sha"] == "S"  # overridden
    assert "artifacts_commits" not in reg.copy_mode.keys
    assert "deprecated" in caplog.text


def test_artifacts_stitches_copy_group_override_wins_over_legacy_alias(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        reg = load_keymap_registry(
            {
                "keymaps": {
                    "modes": {
                        "copy_mode": {
                            "keys": {
                                "artifacts_commits": {"sha": "S"},  # legacy wire key
                                "artifacts_stitches": {"sha": "T"},
                            },
                        },
                    },
                },
            }
        )
    stitches_keys = reg.copy_mode.keys["artifacts_stitches"]
    assert isinstance(stitches_keys, dict)
    assert stitches_keys["sha"] == "T"
    assert "deprecated" in caplog.text
    assert "ignored" in caplog.text
