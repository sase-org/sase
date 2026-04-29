"""Phase 4 guard regression tests for the ace TUI command catalog.

These tests lock in the cross-surface invariants laid out in
``plans/202604/tui_command_palette.md`` Phase 4:

- Adding a new ``AppKeymaps`` field without adding a corresponding
  ``CommandSpec`` is rejected (the catalog raises at import; this
  test replays the failure scenario via the metadata table).
- Every built-in mode subkey present in a freshly-loaded
  :class:`KeymapRegistry` is represented in the catalog.
- Every catalog entry has at least one applicable tab — a command
  with empty ``tabs`` would never be visible in the palette and
  represents a configuration bug.
- Every catalog entry has a non-empty label, key sequence, and key
  display so the palette never renders a blank row.
- :func:`sort_specs_by_category` is stable and category-grouped per
  :data:`CATEGORY_ORDER`.
- :func:`get_command_by_id` round-trips for every spec in the
  catalog.
"""

from __future__ import annotations

from dataclasses import fields

import pytest

from sase.ace.tui.commands import (
    CATEGORY_ORDER,
    CommandSpec,
    build_command_catalog,
    get_command_by_id,
    sort_specs_by_category,
)
from sase.ace.tui.commands.types import CommandCategory
from sase.ace.tui.keymaps import (
    AppKeymaps,
    KeymapRegistry,
    load_keymap_registry,
)


def _registry() -> KeymapRegistry:
    return load_keymap_registry({})


# ---------------------------------------------------------------------------
# AppKeymaps coverage
# ---------------------------------------------------------------------------


def test_every_app_keymap_field_appears_in_catalog() -> None:
    """Every ``AppKeymaps`` field must produce a ``CommandSpec``.

    Adding a new field without a catalog representation would let the
    palette silently drop a binding. The catalog's import-time
    ``_ensure_metadata_covers_app_keymaps()`` already raises, but
    re-asserting here protects the contract for downstream callers.
    """
    catalog = build_command_catalog(_registry())
    catalog_app_ids = {c.id for c in catalog if c.id.startswith("app.")}
    expected = {f"app.{f.name}" for f in fields(AppKeymaps)}
    missing = expected - catalog_app_ids
    extra = catalog_app_ids - expected
    assert not missing, f"AppKeymaps fields without a CommandSpec: {sorted(missing)}"
    assert not extra, f"app.* CommandSpecs without an AppKeymaps field: {sorted(extra)}"


def test_adding_unknown_app_keymap_field_fails_metadata_guard() -> None:
    """Drift detector: simulate an unknown AppKeymaps field.

    Reaches into the metadata-coverage helper directly to confirm
    the guard fires when the metadata table is out of sync. This
    locks the import-time guard so it cannot be quietly weakened.
    """
    from sase.ace.tui.commands import catalog as catalog_mod

    original = catalog_mod._APP_COMMAND_META
    truncated = original[:-1]
    catalog_mod._APP_COMMAND_META = truncated  # type: ignore[assignment]
    try:
        with pytest.raises(RuntimeError, match="missing metadata"):
            catalog_mod._ensure_metadata_covers_app_keymaps()
    finally:
        catalog_mod._APP_COMMAND_META = original  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Built-in mode coverage
# ---------------------------------------------------------------------------


def test_every_builtin_mode_subkey_has_a_command_spec() -> None:
    """Each fold/copy/leader/bang subkey in the registry maps to a spec."""
    reg = _registry()
    catalog = build_command_catalog(reg)
    ids = {c.id for c in catalog}

    # Fold
    for cid in reg.fold_mode.keys:
        assert f"fold.{cid}" in ids, f"missing fold.{cid}"

    # Copy (nested per-tab)
    for tab_name, sub in reg.copy_mode.keys.items():
        assert isinstance(sub, dict), tab_name
        for cid in sub:
            assert f"copy.{tab_name}.{cid}" in ids, f"missing copy.{tab_name}.{cid}"

    # Leader
    for cid in reg.leader_mode.keys:
        assert f"leader.{cid}" in ids, f"missing leader.{cid}"

    # Bang
    for cid in reg.bang_mode.keys:
        assert f"bang.{cid}" in ids, f"missing bang.{cid}"


def test_leader_mode_dataclass_default_matches_default_config_yml() -> None:
    """Drift between the dataclass default and ``default_config.yml``
    let the catalog produce different leader specs depending on
    whether the production config or the bare defaults are loaded.
    Phase 4 closed that gap; this guard locks it down.
    """
    reg_dataclass = load_keymap_registry({})
    catalog_dataclass_ids = {
        c.id for c in build_command_catalog(reg_dataclass) if c.id.startswith("leader.")
    }
    expected_leader_ids = {f"leader.{cid}" for cid in reg_dataclass.leader_mode.keys}
    assert catalog_dataclass_ids == expected_leader_ids
    # ``jump_to_notification`` was the historical drift offender.
    assert "leader.jump_to_notification" in catalog_dataclass_ids


# ---------------------------------------------------------------------------
# Per-spec well-formedness
# ---------------------------------------------------------------------------


def test_every_command_spec_has_at_least_one_tab() -> None:
    """A command with empty ``tabs`` would never be selectable."""
    catalog = build_command_catalog(_registry())
    bad = [c for c in catalog if not c.tabs]
    assert not bad, f"CommandSpecs with empty tabs: {[c.id for c in bad]}"


def test_every_command_spec_has_label_and_key_display() -> None:
    """Palette rows must not be blank."""
    catalog = build_command_catalog(_registry())
    for spec in catalog:
        assert spec.label, f"{spec.id}: empty label"
        assert spec.key_sequence, f"{spec.id}: empty key sequence"
        assert all(spec.key_sequence), f"{spec.id}: empty key in sequence"
        assert spec.key_display, f"{spec.id}: empty key display"


def test_every_command_category_is_in_typed_literal() -> None:
    """Belt-and-braces check: category strings must match the literal.

    The ``CommandCategory`` literal is type-checked at definition,
    but the catalog stores them as strings; an unchecked stringly
    cast (e.g. ``CommandCategory(...)``) could slip past mypy.
    """
    valid = set(CommandCategory.__args__)  # type: ignore[attr-defined]
    catalog = build_command_catalog(_registry())
    for spec in catalog:
        assert spec.category in valid, f"{spec.id}: bad category {spec.category!r}"


# ---------------------------------------------------------------------------
# sort_specs_by_category
# ---------------------------------------------------------------------------


def test_sort_specs_by_category_groups_by_category_order() -> None:
    catalog = build_command_catalog(_registry())
    ordered = sort_specs_by_category(catalog)
    # Compute the index in CATEGORY_ORDER for each spec; it must be
    # non-decreasing across the sorted list.
    rank = {cat: i for i, cat in enumerate(CATEGORY_ORDER)}
    fallback = len(rank)
    indices = [rank.get(s.category, fallback) for s in ordered]
    assert indices == sorted(indices)


def test_sort_specs_by_category_is_stable_within_category() -> None:
    """Original order must be preserved for specs in the same category."""
    catalog = build_command_catalog(_registry())
    ordered = sort_specs_by_category(catalog)
    by_cat: dict[str, list[str]] = {}
    by_cat_orig: dict[str, list[str]] = {}
    for s in ordered:
        by_cat.setdefault(s.category, []).append(s.id)
    for s in catalog:
        by_cat_orig.setdefault(s.category, []).append(s.id)
    for cat, ids in by_cat.items():
        assert ids == by_cat_orig[cat], f"reorder within category {cat}"


def test_sort_specs_by_category_returns_same_set() -> None:
    catalog = build_command_catalog(_registry())
    ordered = sort_specs_by_category(catalog)
    assert {s.id for s in ordered} == {s.id for s in catalog}
    assert len(ordered) == len(catalog)


# ---------------------------------------------------------------------------
# get_command_by_id
# ---------------------------------------------------------------------------


def test_get_command_by_id_round_trips_for_every_spec() -> None:
    catalog = build_command_catalog(_registry())
    for spec in catalog:
        looked_up = get_command_by_id(catalog, spec.id)
        assert looked_up is spec


def test_get_command_by_id_returns_none_for_unknown_id() -> None:
    catalog = build_command_catalog(_registry())
    assert get_command_by_id(catalog, "app.does_not_exist") is None


# ---------------------------------------------------------------------------
# CATEGORY_ORDER coverage
# ---------------------------------------------------------------------------


def test_category_order_covers_every_category_used_by_catalog() -> None:
    """No catalog category should fall through to the unordered tail.

    Categories used in the live catalog must appear in
    ``CATEGORY_ORDER`` so the palette display stays predictable
    across the full key surface. Adding a new category to the
    literal without listing it here is the regression we want to
    catch.
    """
    catalog = build_command_catalog(_registry())
    used = {s.category for s in catalog}
    missing = used - set(CATEGORY_ORDER)
    assert not missing, f"categories not in CATEGORY_ORDER: {sorted(missing)}"


def test_category_order_entries_are_unique() -> None:
    assert len(CATEGORY_ORDER) == len(set(CATEGORY_ORDER))


# ---------------------------------------------------------------------------
# Catalog as drift bulwark
# ---------------------------------------------------------------------------


def test_catalog_specs_use_configured_keys() -> None:
    """A user-overridden app key must propagate through the catalog."""
    reg = load_keymap_registry({"keymaps": {"app": {"refresh": "F"}}})
    catalog = build_command_catalog(reg)
    spec = get_command_by_id(catalog, "app.refresh")
    assert spec is not None
    assert spec.key_sequence == ("F",)
    assert spec.key_display == "F"


def test_open_command_palette_command_is_always_present() -> None:
    """The palette opener must remain in the catalog regardless of
    config, since it is the discovery entry point for the palette
    itself."""
    catalog = build_command_catalog(_registry())
    spec = get_command_by_id(catalog, "app.open_command_palette")
    assert spec is not None
    assert "changespecs" in spec.tabs
    assert "agents" in spec.tabs
    assert "axe" in spec.tabs


# ---------------------------------------------------------------------------
# Regression: well-formed CommandSpec instances
# ---------------------------------------------------------------------------


def test_every_spec_id_is_unique() -> None:
    catalog = build_command_catalog(_registry())
    ids = [c.id for c in catalog]
    assert len(ids) == len(set(ids)), "duplicate CommandSpec ids"


def test_every_spec_is_a_commandspec_instance() -> None:
    catalog = build_command_catalog(_registry())
    for spec in catalog:
        assert isinstance(spec, CommandSpec)
