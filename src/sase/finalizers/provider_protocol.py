"""Version of the host-to-provider envelope spoken by finalizer plugins.

This is deliberately **not** ``FINALIZER_WIRE_SCHEMA_VERSION``. That constant
mirrors the Rust core's finalizer wire (plan input, instance spec, context,
submission) and moves whenever ``sase-core`` rev's its own protocol. This one
versions the JSON envelope the host exchanges with external
``sase_finalizers`` providers over stdin/stdout, whose fields (``operation``,
``provider_ref``, ``status``, ``payload``) do not appear in the core wire at
all.

They were one constant until the core bumped its wire to 2 for typed
deferrals, which would have rejected every installed plugin's ``1``-stamped
response for a change that does not touch the plugin envelope. Keep them
apart: a core wire bump must not invalidate published plugins, and a plugin
envelope change must not imply anything about the core.
"""

from __future__ import annotations

FINALIZER_PROVIDER_PROTOCOL_VERSION = 1


__all__ = ["FINALIZER_PROVIDER_PROTOCOL_VERSION"]
