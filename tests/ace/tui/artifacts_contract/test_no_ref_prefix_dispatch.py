"""Behavioral TUI modules must not dispatch on the ``ref:`` pane-id prefix."""

from __future__ import annotations

from pathlib import Path
import re

TUI_ROOT = Path(__file__).resolve().parents[4] / "src" / "sase" / "ace" / "tui"

# Parsing or rendering a canonical artifact-ref / pane-id string may still
# mention ``ref:``. These files are identity, descriptors, or documented
# compatibility aliases — not behavioral pane dispatch.
_ALLOWLIST = {
    TUI_ROOT / "_artifact_tab_model.py",
    TUI_ROOT / "_artifact_tab_contract.py",
    TUI_ROOT / "_artifact_tab_descriptors.py",
    TUI_ROOT / "artifact_tabs.py",
    TUI_ROOT / "widgets" / "artifacts" / "entry_navigation.py",
    TUI_ROOT / "widgets" / "artifacts" / "plans_list.py",
    TUI_ROOT / "widgets" / "artifacts" / "plans_pane.py",
    TUI_ROOT / "widgets" / "artifacts" / "plans_filter_session.py",
    TUI_ROOT / "actions" / "artifacts_plans.py",
    TUI_ROOT / "actions" / "_artifacts_beads_browse.py",
    TUI_ROOT / "actions" / "_state_init_navigation.py",
    TUI_ROOT / "actions" / "clipboard" / "_palette_artifacts.py",
    # Compatibility alias for a historical copy-group name, not pane dispatch.
    TUI_ROOT / "copy_targets.py",
    # Parses the ``ref:<kind>`` pane-id encoding for artifact-ref rendering.
    TUI_ROOT / "actions" / "clipboard" / "_artifact_reference_resolution.py",
}

_DISPATCH_RE = re.compile(
    r"""startswith\(\s*['\"]ref:['\"]\s*\)"""
    r"""|removeprefix\(\s*['\"]ref:['\"]\s*\)"""
    r"""|\.startswith\(\s*['\"]artifacts_ref:['\"]\s*\)"""
)


def test_behavioral_modules_do_not_dispatch_on_ref_prefix() -> None:
    offenders: list[str] = []
    for path in TUI_ROOT.rglob("*.py"):
        if path in _ALLOWLIST or path.name.endswith(".pyi"):
            continue
        text = path.read_text(encoding="utf-8")
        if _DISPATCH_RE.search(text):
            offenders.append(str(path.relative_to(TUI_ROOT)))
    assert offenders == []
