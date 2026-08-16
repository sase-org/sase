"""ACE keymap action-rename checks for ``sase doctor``."""

from __future__ import annotations

from sase.ace.tui.keymaps.registry import LEGACY_APP_KEY_ALIASES
from sase.config import load_merged_config
from sase.diagnostics import CheckStatus, DiagnosticCheck
from sase.doctor.checks_config_common import MAX_DETAIL_ROWS


def check_config_keymap_actions() -> DiagnosticCheck:
    """Flag ``ace.keymaps.app`` overrides that name a retired action.

    sase-m6.9 unified the six Artifacts verbs whose meanings were inverted
    between Patch and its siblings (e.g. ``stitches_refresh``,
    ``beads_copy_bug``) onto single contract actions (``refresh``,
    ``artifacts_copy_reference``). A user override naming the old action
    still loads — ``load_keymap_registry`` transparently rebinds it to the
    canonical action — but it silently stops meaning what the user
    originally bound it for, so this surfaces it as an actionable warning
    rather than a config-load debug log line.
    """
    config = load_merged_config()
    ace = config.get("ace", {})
    keymaps = ace.get("keymaps", {}) if isinstance(ace, dict) else {}
    app_overrides = keymaps.get("app", {}) if isinstance(keymaps, dict) else {}
    if not isinstance(app_overrides, dict):
        app_overrides = {}

    problems = [
        f"{legacy} -> {canonical}"
        for legacy, canonical in LEGACY_APP_KEY_ALIASES.items()
        if legacy in app_overrides
    ]

    status: CheckStatus = "WARN" if problems else "OK"
    summary = (
        f"{len(problems)} renamed keymap action(s) found in ace.keymaps.app"
        if problems
        else "no renamed keymap actions configured"
    )
    next_steps = (
        (
            "Run `sase config migrate-keymap-actions` to rewrite the reported "
            "keys in place, then rerun `sase doctor -C config.keymap_actions`.",
        )
        if problems
        else ()
    )

    return DiagnosticCheck(
        id="config.keymap_actions",
        group="config",
        status=status,
        title="Keymap action renames",
        summary=summary,
        details=tuple(problems[:MAX_DETAIL_ROWS]),
        next_steps=next_steps,
        data={"problems": problems},
    )
