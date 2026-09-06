"""Temporary offline migration kit for the canonical-only cutover.

TEMPORARY PACKAGE: deletion owner sase-x7.14 (enforce-and-verify). That phase
archives and then deletes this entire package, the ``sase migrate`` command
group, the core ``migration`` module, and its bindings once the cutover
completes. Nothing here may be imported at interpreter startup, plugin
discovery, completion, agent launch, or any ordinary read -- every caller
imports this package lazily from inside a dispatch function.
"""

from __future__ import annotations
