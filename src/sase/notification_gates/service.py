"""Durable constructor and revision service for notification gates.

Facade preserving the original import path. The implementation now lives in
:mod:`sase.notification_gates.service_creation` (creation lifecycle),
:mod:`sase.notification_gates.service_assembly` (envelope assembly),
:mod:`sase.notification_gates.service_evaluation` (automatic-gate
evaluation), and :mod:`sase.notification_gates._service_shared` (shared
primitives); this module re-exports their public names and nothing
``_``-private.
"""

from sase.notification_gates._service_shared import (
    CREATION_JOURNAL_SCHEMA_VERSION as CREATION_JOURNAL_SCHEMA_VERSION,
)
from sase.notification_gates.service_creation import create_gate as create_gate

__all__ = ["create_gate"]
