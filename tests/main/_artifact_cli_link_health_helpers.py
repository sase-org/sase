"""Shared helpers for artifact-link doctor health tests."""

from __future__ import annotations

import pytest

_RESOLVE_CLI_REFERENCE_TARGETS = (
    "sase.artifact_cli.link_health.resolve_cli_reference",
    "sase.artifact_cli._link_health_refs.resolve_cli_reference",
    "sase.artifact_cli._link_health_tables.resolve_cli_reference",
    "sase.artifact_cli._link_health_coverage.resolve_cli_reference",
)


def stub_resolve_cli_reference(
    monkeypatch: pytest.MonkeyPatch, resolve: object
) -> None:
    for target in _RESOLVE_CLI_REFERENCE_TARGETS:
        monkeypatch.setattr(target, resolve)
