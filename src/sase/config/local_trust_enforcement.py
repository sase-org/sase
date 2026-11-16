"""Synchronous trust enforcement for project-local executable config.

Phase ``hook-enforcement`` activates the ``local_config_command_trust``
sunset flag. When the flag is enabled, local command-bearing contributions
require a current human acknowledgment; otherwise they are filtered before
merging and before the independent file-hook and config-macro loaders
consume raw layers.

``load_config_layers()`` stays raw for provenance inspection and
feature-flag bootstrap. This module provides the effective-local adapter
that executable consumers use instead.

This module is a stable facade: implementation lives in
``_local_trust_enforcement_shared``,
``local_trust_enforcement_evaluation``, and
``local_trust_enforcement_flag_on``. Import paths for the public names
below are unchanged.
"""

from __future__ import annotations

from sase.config._local_trust_enforcement_shared import (
    LocalTrustEvaluation,
    is_local_command_trust_enabled,
)
from sase.config.local_trust_enforcement_evaluation import (
    effective_local_layer,
    evaluate_local_trust_for_path,
    validate_trust_descriptor,
)

__all__ = [
    "LocalTrustEvaluation",
    "effective_local_layer",
    "evaluate_local_trust_for_path",
    "is_local_command_trust_enabled",
    "validate_trust_descriptor",
]
