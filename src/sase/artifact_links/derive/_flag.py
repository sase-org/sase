"""Beta-flag gate for artifact-link derivation call sites."""

from __future__ import annotations


def artifact_link_derivation_enabled() -> bool:
    """Return whether a call site may derive and persist candidate rows.

    Each call site owns this check itself; the derivation rules and the
    ``derive_candidate_links`` entry point never consult the flag.
    """

    from sase.feature_flags import FeatureFlag, current_flags

    return current_flags().enabled(FeatureFlag.artifact_link_derivation)
