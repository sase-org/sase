"""Shared helpers for the split keymap-registry builder stages."""

import logging


log = logging.getLogger("sase.ace.tui.keymaps.registry")


def migrate_key_aliases(
    keys: dict[str, str | dict[str, str]],
    aliases: dict[str, str],
    *,
    context: str,
) -> dict[str, str | dict[str, str]]:
    """Normalize legacy keymap action ids to their canonical names."""
    migrated = dict(keys)
    for legacy_name, canonical_name in aliases.items():
        if legacy_name not in migrated:
            continue
        legacy_value = migrated.pop(legacy_name)
        if canonical_name in migrated:
            log.warning(
                "%s keymap action %r is deprecated and ignored because %r is "
                "configured",
                context,
                legacy_name,
                canonical_name,
            )
            continue
        migrated[canonical_name] = legacy_value
        log.warning(
            "%s keymap action %r is deprecated; treating it as %r",
            context,
            legacy_name,
            canonical_name,
        )
    return migrated
