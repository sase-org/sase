"""Release closeout guards for daemon rollout compatibility."""

from __future__ import annotations

import tomllib
from pathlib import Path

from sase.daemon.constants import (
    LOCAL_DAEMON_EXPECTED_PROJECTION_READ_SCHEMA_VERSION,
    LOCAL_DAEMON_EXPECTED_PROJECTION_WRITE_SCHEMA_VERSION,
    LOCAL_DAEMON_MAX_SUPPORTED_SCHEMA_VERSION,
    LOCAL_DAEMON_MIN_SUPPORTED_SCHEMA_VERSION,
)
from sase.daemon.release_contract import (
    SASE_CORE_RS_DEPENDENCY,
    SASE_CORE_RS_DEPENDENCY_NAME,
    SASE_CORE_RS_SUPPORTED_SPECIFIER,
    release_contract_payload,
)
from sase.host.wire import PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION


def test_sase_core_rs_dependency_matches_release_contract() -> None:
    data = tomllib.loads((_repo_root() / "pyproject.toml").read_text())
    dependencies = data["project"]["dependencies"]

    matches = [
        dependency
        for dependency in dependencies
        if dependency.startswith(SASE_CORE_RS_DEPENDENCY_NAME)
    ]

    assert matches == [SASE_CORE_RS_DEPENDENCY]
    assert matches[0].removeprefix(SASE_CORE_RS_DEPENDENCY_NAME) == (
        SASE_CORE_RS_SUPPORTED_SPECIFIER
    )


def test_release_contract_reports_supported_wire_and_package_ranges() -> None:
    payload = release_contract_payload()

    assert payload["sase_core_rs"]["dependency"] == SASE_CORE_RS_DEPENDENCY
    assert payload["local_daemon"] == {
        "min_supported_schema_version": LOCAL_DAEMON_MIN_SUPPORTED_SCHEMA_VERSION,
        "max_supported_schema_version": LOCAL_DAEMON_MAX_SUPPORTED_SCHEMA_VERSION,
        "expected_projection_read_schema_version": (
            LOCAL_DAEMON_EXPECTED_PROJECTION_READ_SCHEMA_VERSION
        ),
        "expected_projection_write_schema_version": (
            LOCAL_DAEMON_EXPECTED_PROJECTION_WRITE_SCHEMA_VERSION
        ),
    }
    assert payload["provider_host"]["ipc_wire_schema_version"] == (
        PROVIDER_HOST_IPC_WIRE_SCHEMA_VERSION
    )


def test_release_docs_name_closeout_controls_and_package_range() -> None:
    local_daemon = (_repo_root() / "docs" / "local_daemon.md").read_text()
    plugins = (_repo_root() / "docs" / "plugins.md").read_text()

    assert "sase daemon rollout --json" in local_daemon
    assert SASE_CORE_RS_DEPENDENCY in local_daemon
    assert "## Provider Host Rollout" in plugins
    for operation in (
        "llm.metadata",
        "xprompt.catalog",
        "vcs.query",
        "workspace.metadata",
        "workspace.resolve_ref",
    ):
        assert operation in plugins


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]
