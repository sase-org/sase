"""Tests for the service-platform doctor check."""

from __future__ import annotations

from sase.doctor.checks_service_platform import check_service_platform
from sase.feature_flags import override_flags


def test_service_platform_check_skips_when_beta_flag_is_off() -> None:
    with override_flags(service_host=False):
        check = check_service_platform()

    assert check.id == "service.platform"
    assert check.status == "SKIP"
    assert "service_host" in check.summary
