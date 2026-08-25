"""ACE keymap Glossary-scope deprecation check for ``sase doctor``."""

from __future__ import annotations

from sase.config.core import load_config_layers
from sase.diagnostics import CheckStatus, DiagnosticCheck
from sase.doctor.checks_config_common import MAX_DETAIL_ROWS


def check_config_keymap_glossary() -> DiagnosticCheck:
    """Flag config layers that still explicitly set ``ace.keymaps.glossary``.

    The Glossary panel keymap scope is retired: ``default_config.yml`` no
    longer ships bundled defaults for it, and ``load_keymap_registry`` no
    longer builds a ``.glossary`` binding scope from it. The config schema
    still accepts ``ace.keymaps.glossary`` for one release so existing user
    configs do not fail validation, but any customization there is silently
    inert. This inspects the unmerged config layers (not the defaulted
    result) so the warning fires only when a user actually set the key
    themselves, not merely because it is present after defaults are applied.
    """
    problems = []
    for layer in load_config_layers():
        ace = layer.data.get("ace")
        keymaps = ace.get("keymaps") if isinstance(ace, dict) else None
        if isinstance(keymaps, dict) and "glossary" in keymaps:
            location = layer.path or layer.name
            problems.append(f"{location}: ace.keymaps.glossary -> ace.keymaps.memory")

    status: CheckStatus = "WARN" if problems else "OK"
    summary = (
        f"{len(problems)} config layer(s) set the retired ace.keymaps.glossary scope"
        if problems
        else "no ace.keymaps.glossary overrides configured"
    )
    next_steps = (
        (
            "Move any ace.keymaps.glossary customization to ace.keymaps.memory; "
            "the Glossary panel keymap scope no longer builds bindings.",
        )
        if problems
        else ()
    )

    return DiagnosticCheck(
        id="config.keymap_glossary",
        group="config",
        status=status,
        title="Glossary keymap scope",
        summary=summary,
        details=tuple(problems[:MAX_DETAIL_ROWS]),
        next_steps=next_steps,
        data={"problems": problems},
    )
