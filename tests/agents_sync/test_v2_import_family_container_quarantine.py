"""Family members without a container quarantine the imported hood."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sase.agents_sync import v2_importer
from sase.core.agent_identity_facade import AgentIdentitySnapshot

from tests.agents_sync.v2_importer_fixtures import (
    LOCAL_OWNER,
    isolate_local_state,
    published_package,
)


def test_family_member_without_container_quarantines_hood(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, package = published_package(tmp_path)
    isolate_local_state(tmp_path, target, monkeypatch)
    stripped = replace(
        package,
        snapshot=replace(package.snapshot, containers=()),
    )

    result = v2_importer.integrate_v2_hoods(
        target,
        (stripped,),
        identity=AgentIdentitySnapshot(LOCAL_OWNER),
    )

    assert result.hoods_quarantined == 1
    assert result.hoods_imported == 0
    assert any("family container" in diagnostic for diagnostic in result.diagnostics)
