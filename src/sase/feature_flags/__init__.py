"""Public feature-flag API."""

from __future__ import annotations

from sase.feature_flags.env import SASE_FEATURE_FLAGS_ENV
from sase.feature_flags.models import (
    FeatureFlagDecision,
    FeatureFlagDefinition,
    FeatureFlagDiagnostic,
    FeatureFlagEnvError,
    FeatureFlagError,
)
from sase.feature_flags.registry import FeatureFlag
from sase.feature_flags.snapshot import (
    current_flags,
    install_process_feature_flags,
    override_flags,
)


__all__ = [
    "SASE_FEATURE_FLAGS_ENV",
    "FeatureFlag",
    "FeatureFlagDecision",
    "FeatureFlagDefinition",
    "FeatureFlagDiagnostic",
    "FeatureFlagEnvError",
    "FeatureFlagError",
    "current_flags",
    "install_process_feature_flags",
    "override_flags",
]
