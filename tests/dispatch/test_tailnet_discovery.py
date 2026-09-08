"""Tailnet discovery tests for remote dispatch providers."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from sase.dispatch import tailnet_discovery as tailnet_module
from sase.dispatch.config import load_dispatch_config
from sase.dispatch.providers import discover_dispatch_result

FIXTURES = Path(__file__).with_name("fixtures")


def _entry_points_fn(*entry_points: object) -> Any:
    def fake_entry_points(*, group: str) -> tuple[object, ...]:
        assert group == "sase_dispatch"
        return entry_points

    return fake_entry_points


def _tailnet_config(
    *,
    enabled: bool = True,
    selected: list[str] | None = None,
    provider_settings: dict[str, object] | None = None,
) -> Any:
    settings: dict[str, object] = {"enabled": enabled}
    if provider_settings:
        settings.update(provider_settings)
    return load_dispatch_config(
        {
            "dispatch": {
                "providers": {"builtin@tailnet": settings},
                "discovery": {
                    "enabled_providers": (
                        ["builtin@tailnet"] if selected is None else selected
                    )
                },
            }
        }
    )


def _fixture_status(name: str) -> tailnet_module._BoundedCommandResult:
    return tailnet_module._BoundedCommandResult(
        stdout=(FIXTURES / name).read_bytes(),
        returncode=0,
    )


def test_tailnet_discovery_parses_status_and_probes_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_probe(
        endpoint: str,
        *,
        timeout_seconds: float,
        max_response_bytes: int,
        alias: str,
    ) -> tailnet_module._HealthProbeResult:
        del timeout_seconds, max_response_bytes
        if "apollo" in endpoint:
            return tailnet_module._HealthProbeResult(
                compatibility="compatible",
                reason="fleet protocol v1 advertised",
            )
        return tailnet_module._HealthProbeResult(
            compatibility="unknown",
            reason="health probe timed out",
            diagnostic=tailnet_module.MachineDiagnostic(
                code="tailnet_probe_timeout",
                severity="warning",
                alias=alias,
                message=f"{alias} health probe failed: health probe timed out",
            ),
        )

    monkeypatch.setattr(
        tailnet_module,
        "_run_tailscale_status",
        lambda config, timeout: _fixture_status("tailscale_status_basic.json"),
    )
    monkeypatch.setattr(tailnet_module, "_probe_tailnet_health", fake_probe)

    result = discover_dispatch_result(
        config=_tailnet_config(),
        entry_points_fn=_entry_points_fn(),
    )

    by_endpoint = {candidate.endpoint: candidate for candidate in result.candidates}
    assert list(by_endpoint) == [
        "https://apollo.tail297af1.ts.net",
        "https://pixel.tail297af1.ts.net",
    ]
    assert (
        "compatibility=compatible"
        in by_endpoint["https://apollo.tail297af1.ts.net"].detail
    )
    assert "tailscale=offline" in by_endpoint["https://pixel.tail297af1.ts.net"].detail
    assert all("athena" not in candidate.endpoint for candidate in result.candidates)
    codes = [diagnostic.code for diagnostic in result.diagnostics]
    assert "tailnet_peer_offline" in codes
    assert "tailnet_peer_os_advisory" in codes


def test_tailnet_discovery_defensively_handles_missing_and_extra_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tailnet_module,
        "_run_tailscale_status",
        lambda config, timeout: _fixture_status("tailscale_status_missing_fields.json"),
    )
    monkeypatch.setattr(
        tailnet_module,
        "_probe_tailnet_health",
        lambda endpoint, **kwargs: tailnet_module._HealthProbeResult(
            compatibility="compatible",
            reason="fleet protocol v1 advertised",
        ),
    )

    result = discover_dispatch_result(
        config=_tailnet_config(),
        entry_points_fn=_entry_points_fn(),
    )

    assert [candidate.endpoint for candidate in result.candidates] == [
        "https://extra.tail297af1.ts.net"
    ]
    assert [diagnostic.code for diagnostic in result.diagnostics].count(
        "tailnet_peer_dns_invalid"
    ) == 2


@pytest.mark.parametrize(
    ("status_result", "expected_code"),
    [
        (
            tailnet_module._BoundedCommandResult(
                error_code="status_unavailable",
                error_message="tailscale CLI is not installed or not on PATH",
            ),
            "tailnet_status_unavailable",
        ),
        (
            tailnet_module._BoundedCommandResult(stdout=b"not json", returncode=0),
            "tailnet_status_malformed",
        ),
        (
            tailnet_module._BoundedCommandResult(
                error_code="status_output_too_large",
                error_message="tailscale status --json exceeded the output size limit",
            ),
            "tailnet_status_output_too_large",
        ),
    ],
)
def test_tailnet_discovery_reports_status_failures(
    monkeypatch: pytest.MonkeyPatch,
    status_result: tailnet_module._BoundedCommandResult,
    expected_code: str,
) -> None:
    monkeypatch.setattr(
        tailnet_module,
        "_run_tailscale_status",
        lambda config, timeout: status_result,
    )

    result = discover_dispatch_result(
        config=_tailnet_config(),
        entry_points_fn=_entry_points_fn(),
    )

    assert result.candidates == ()
    assert [diagnostic.code for diagnostic in result.diagnostics] == [expected_code]


def test_tailnet_command_runner_enforces_output_size_and_timeout() -> None:
    oversized = tailnet_module._run_command_bounded(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('x' * 10000)",
        ],
        timeout_seconds=5,
        max_stdout_bytes=4,
    )
    timed_out = tailnet_module._run_command_bounded(
        [sys.executable, "-c", "import time; time.sleep(1)"],
        timeout_seconds=0.01,
        max_stdout_bytes=1024,
    )

    assert oversized.error_code == "status_output_too_large"
    assert timed_out.error_code == "status_timeout"


def test_tailnet_health_classifies_fleet_advertisement() -> None:
    compatible = tailnet_module._classify_tailnet_health_payload(
        {"status": "ok", "fleet": {"supported_protocol_versions": [1]}},
        alias="apollo",
    )
    unknown = tailnet_module._classify_tailnet_health_payload(
        {"status": "ok"},
        alias="old-gateway",
    )
    incompatible = tailnet_module._classify_tailnet_health_payload(
        {"status": "ok", "fleet": {"supported_protocol_versions": [99]}},
        alias="future-gateway",
    )
    unrelated = tailnet_module._classify_tailnet_health_payload(
        {"hello": "world"},
        alias="web-server",
    )

    assert compatible.compatibility == "compatible"
    assert unknown.compatibility == "unknown"
    assert unknown.diagnostic is not None
    assert unknown.diagnostic.code == "tailnet_probe_fleet_unknown"
    assert incompatible.compatibility == "incompatible"
    assert incompatible.diagnostic is not None
    assert incompatible.diagnostic.code == "tailnet_probe_fleet_incompatible"
    assert unrelated.compatibility == "incompatible"
    assert unrelated.diagnostic is not None
    assert unrelated.diagnostic.code == "tailnet_probe_unrelated_service"


def test_tailnet_probe_reports_unrelated_non_json_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Response:
        status = 200

        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, size: int) -> bytes:
            del size
            return b"<html>not json</html>"

    monkeypatch.setattr(
        tailnet_module.urllib.request,
        "urlopen",
        lambda request, timeout: _Response(),
    )

    probe = tailnet_module._probe_tailnet_health(
        "https://web.example.test",
        timeout_seconds=1,
        max_response_bytes=1024,
        alias="web",
    )

    assert probe.compatibility == "incompatible"
    assert probe.diagnostic is not None
    assert probe.diagnostic.code == "tailnet_probe_unrelated_service"


def test_tailnet_status_command_uses_argv_without_shell() -> None:
    assert tailnet_module._tailscale_status_argv({}) == (
        "tailscale",
        "status",
        "--json",
    )
    assert tailnet_module._tailscale_status_argv(
        {"command": "tailscale --socket=/tmp/tailscaled.sock"}
    ) == (
        "tailscale",
        "--socket=/tmp/tailscaled.sock",
        "status",
        "--json",
    )
