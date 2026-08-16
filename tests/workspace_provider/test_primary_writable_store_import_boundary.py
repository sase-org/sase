"""Import-boundary regression gate for primary writable-store resolution (sase-mq.7).

``sase.workspace_provider.ownership.writable_beads_dir``/``writable_plans_dir``/
``writable_checkout_dir``/``writable_sidecar_root``/``writable_kind_root`` are the
only sanctioned way to turn an :class:`OperationContext` into a path SASE-initiated
code may write to. Every caller outside the allowlist below has already been
audited (phases sase-mq.2, sase-mq.5, sase-mq.6) to go through a leased or
primary-sidecar-sync context rather than resolving a primary path directly. A
new caller importing these names bypasses that review, so this test fails
closed the moment one appears; drop the stale entry the same way phase
sase-mq's own notes describe for the analogous symvision ``--epic-symbol``
allowlist once a phase closes and a symbol's last caller goes away.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = _REPO_ROOT / "src"

_SENSITIVE_NAMES = frozenset(
    {
        "writable_beads_dir",
        "writable_checkout_dir",
        "writable_kind_root",
        "writable_plans_dir",
        "writable_sidecar_root",
    }
)

#: Modules already audited to resolve a writable path only from a leased
#: operational context or an opt-in primary-sidecar-sync context, never from
#: primary #0 directly. Keep in sync with the actual importer set; a stale
#: entry (its one caller removed) is as much a bug as a missing one.
_ALLOWED_IMPORTERS = frozenset(
    {
        "sase/_sidecar_auto_sync.py",
        "sase/bead/background_store.py",
        "sase/external_mirror/issues.py",
        "sase/workspace_provider/__init__.py",
    }
)


def _sensitive_writable_store_importers() -> frozenset[str]:
    importers: set[str] = set()
    for path in sorted(_SRC_DIR.rglob("*.py")):
        relative = path.relative_to(_SRC_DIR).as_posix()
        if relative == "sase/workspace_provider/ownership.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            module = node.module or ""
            is_absolute_match = module in {
                "sase.workspace_provider.ownership",
                "sase.workspace_provider",
            }
            is_relative_match = node.level > 0 and module in {"ownership", ""}
            if not (is_absolute_match or is_relative_match):
                continue
            names = {alias.name for alias in node.names}
            if names & _SENSITIVE_NAMES:
                importers.add(relative)
    return frozenset(importers)


def test_writable_store_resolution_importers_match_the_audited_allowlist() -> None:
    found = _sensitive_writable_store_importers()

    unaudited = found - _ALLOWED_IMPORTERS
    assert not unaudited, (
        "new automated import of primary writable-store resolution outside "
        f"the sase-mq.7 audit allowlist: {sorted(unaudited)}; either route "
        "the write through an existing leased/sidecar-sync helper or add "
        "the module to _ALLOWED_IMPORTERS after auditing it"
    )

    stale = _ALLOWED_IMPORTERS - found
    assert not stale, (
        f"sase-mq.7 allowlist entries no longer import writable-store "
        f"resolution and are stale: {sorted(stale)}"
    )
