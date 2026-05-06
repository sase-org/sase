"""Tests for the ace TUI command catalog (Phase 1).

Verifies that :func:`build_command_catalog` produces a stable list of
:class:`CommandSpec` entries that:

- Cover every :class:`AppKeymaps` field exactly once.
- Include all 10 saved-query digit bindings.
- Cover every built-in mode subkey (fold, copy nested per-tab, leader,
  bang) and every valid user-defined custom mode command.
- Carry a non-empty key sequence and a stable id.
"""

from __future__ import annotations

from dataclasses import fields

from sase.ace.tui.commands import (
    CommandSpec,
    build_command_catalog,
    iter_app_commands,
    iter_digit_commands,
    iter_mode_commands,
)
from sase.ace.tui.commands.catalog import _format_key_sequence
from sase.ace.tui.keymaps import (
    AppKeymaps,
    KeymapRegistry,
    load_builtin_app_defaults,
    load_keymap_registry,
)


def _registry() -> KeymapRegistry:
    return load_keymap_registry({})


# --- App command coverage ---


def test_every_app_keymap_has_a_command_spec() -> None:
    """Every AppKeymaps field must be represented exactly once."""
    catalog = list(iter_app_commands(_registry()))
    seen = {c.id for c in catalog}
    expected = {f"app.{f.name}" for f in fields(AppKeymaps)}
    assert seen == expected


def test_app_command_spec_uses_configured_key() -> None:
    """A CommandSpec's key sequence must reflect the merged keymap."""
    reg = load_keymap_registry({"keymaps": {"app": {"next_changespec": "B"}}})
    by_id = {c.id: c for c in iter_app_commands(reg)}
    assert by_id["app.next_changespec"].key_sequence == ("B",)
    assert by_id["app.next_changespec"].key_display == "B"


def test_open_command_palette_command_uses_default_alternatives() -> None:
    """The palette opener command picks up both default key alternatives."""
    by_id = {c.id: c for c in iter_app_commands(_registry())}
    spec = by_id["app.open_command_palette"]
    assert spec.key_sequence == ("colon,semicolon",)
    assert spec.key_display == ": / ;"


# --- Digit commands ---


def test_digit_commands_cover_all_ten() -> None:
    digits = list(iter_digit_commands())
    assert {c.id for c in digits} == {f"saved_query.{d}" for d in range(10)}
    assert all(c.executor.kind == "saved_query" for c in digits)


# --- Built-in mode coverage ---


def test_fold_mode_commands_cover_every_subkey() -> None:
    reg = _registry()
    fold_specs = [
        c
        for c in iter_mode_commands(reg)
        if c.id.startswith("fold.") and c.executor.kind == "fold_mode_key"
    ]
    expected = {f"fold.{cid}" for cid in reg.fold_mode.keys}
    assert {c.id for c in fold_specs} == expected
    # Every fold key sequence is (z, subkey)
    for spec in fold_specs:
        assert spec.key_sequence[0] == reg.fold_mode.prefix
        assert len(spec.key_sequence) == 2


def test_copy_mode_commands_per_tab_scope() -> None:
    reg = _registry()
    copy_specs = [
        c
        for c in iter_mode_commands(reg)
        if c.id.startswith("copy.") and c.executor.kind == "copy_mode_key"
    ]
    by_id = {c.id: c for c in copy_specs}
    # Each per-tab subdict produces commands tagged with that single tab.
    assert by_id["copy.changespecs.bug"].tabs == ("changespecs",)
    assert by_id["copy.agents.name"].tabs == ("agents",)
    assert by_id["copy.axe.visible"].tabs == ("axe",)
    # Coverage for every nested key.
    expected: set[str] = set()
    for tab_name, sub in reg.copy_mode.keys.items():
        if isinstance(sub, dict):
            for cid in sub:
                expected.add(f"copy.{tab_name}.{cid}")
    assert {c.id for c in copy_specs} == expected


def test_leader_mode_commands_cover_every_subkey() -> None:
    reg = _registry()
    leader_specs = [c for c in iter_mode_commands(reg) if c.id.startswith("leader.")]
    expected = {f"leader.{cid}" for cid in reg.leader_mode.keys}
    assert {c.id for c in leader_specs} == expected


def test_bang_mode_commands_cover_every_subkey() -> None:
    reg = _registry()
    bang_specs = [c for c in iter_mode_commands(reg) if c.id.startswith("bang.")]
    expected = {f"bang.{cid}" for cid in reg.bang_mode.keys}
    assert {c.id for c in bang_specs} == expected


def test_custom_mode_commands_included() -> None:
    reg = load_keymap_registry(
        {
            "keymaps": {
                "modes": {
                    "my_mode": {
                        "prefix": "semicolon",
                        "keys": {
                            "do_thing": {
                                "key": "t",
                                "shell": "echo hi",
                                "description": "Do a thing",
                            },
                        },
                    },
                },
            },
        }
    )
    specs = [c for c in iter_mode_commands(reg) if c.id.startswith("custom.")]
    assert len(specs) == 1
    spec = specs[0]
    assert spec.id == "custom.my_mode.do_thing"
    assert spec.executor.kind == "custom_mode_key"
    assert spec.executor.mode_name == "my_mode"
    assert spec.executor.command_id == "do_thing"
    assert spec.label == "Do a thing"


# --- build_command_catalog (whole list) ---


def test_build_command_catalog_includes_all_buckets() -> None:
    reg = _registry()
    catalog = build_command_catalog(reg)
    ids = {c.id for c in catalog}
    # App
    for f in fields(AppKeymaps):
        assert f"app.{f.name}" in ids
    # Digit
    for d in range(10):
        assert f"saved_query.{d}" in ids
    # Mode (sample one of each)
    assert "fold.cycle_commits" in ids
    assert "copy.agents.name" in ids
    assert "leader.task_queue" in ids
    assert "bang.toggle_axe" in ids


def test_agent_run_log_leader_command_is_cl_only() -> None:
    catalog = build_command_catalog(_registry())
    spec = next(c for c in catalog if c.id == "leader.agent_run_log")

    assert spec.label == "Agent run log"
    assert spec.key_display == ",A"
    assert spec.tabs == ("changespecs",)
    assert spec.executor.kind == "leader_mode_key"
    assert spec.executor.subkey == "A"


def test_agent_panel_grouping_leader_command_is_agents_only() -> None:
    catalog = build_command_catalog(_registry())
    spec = next(c for c in catalog if c.id == "leader.toggle_agent_panel_grouping")

    assert spec.label == "Toggle agent panel grouping"
    assert spec.key_display == ",g"
    assert spec.tabs == ("agents",)
    assert spec.executor.kind == "leader_mode_key"
    assert spec.executor.subkey == "g"


def test_command_specs_are_well_formed() -> None:
    reg = _registry()
    catalog = build_command_catalog(reg)
    for spec in catalog:
        assert isinstance(spec, CommandSpec)
        assert spec.id
        assert spec.label
        assert spec.key_sequence and all(spec.key_sequence)
        assert spec.key_display
        assert spec.tabs


def test_command_catalog_ids_are_unique() -> None:
    catalog = build_command_catalog(_registry())
    ids = [c.id for c in catalog]
    assert len(ids) == len(set(ids))


# --- key display formatting ---


def test_format_key_sequence_single_char_concat() -> None:
    """Two single-char keys concatenate without separator (``zc``)."""
    assert _format_key_sequence(("z", "c")) == "zc"


def test_format_key_sequence_special_keys_concat() -> None:
    """``percent_sign`` + ``n`` renders as ``%n``."""
    assert _format_key_sequence(("percent_sign", "n")) == "%n"


def test_format_key_sequence_multichar_space_joined() -> None:
    """Multi-char keys (e.g. ``ctrl+d``) get space-joined for readability."""
    assert _format_key_sequence(("ctrl+d", "x")) == "Ctrl+D x"


def test_format_key_sequence_compound_binding_displays_alternatives() -> None:
    """A compound app binding is formatted as alternatives."""
    assert _format_key_sequence(("colon,semicolon",)) == ": / ;"


# --- Source-of-truth guard ---


def test_app_metadata_matches_app_keymaps_after_load() -> None:
    """Catalog construction must not silently drift from AppKeymaps.

    ``catalog.py`` raises at import time if the metadata table doesn't
    cover every ``AppKeymaps`` field; this test re-asserts the contract
    with a freshly-loaded registry to catch runtime regressions.
    """
    defaults = load_builtin_app_defaults()
    reg = load_keymap_registry({})
    catalog = list(iter_app_commands(reg))
    assert len(catalog) == len(defaults)
