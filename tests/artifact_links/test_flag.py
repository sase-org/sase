from __future__ import annotations

from sase.artifact_links.derive import artifact_link_derivation_enabled
from sase.feature_flags import override_flags


def test_disabled_by_default() -> None:
    with override_flags():
        assert artifact_link_derivation_enabled() is False


def test_enabled_when_overridden_on() -> None:
    with override_flags(artifact_link_derivation=True):
        assert artifact_link_derivation_enabled() is True
