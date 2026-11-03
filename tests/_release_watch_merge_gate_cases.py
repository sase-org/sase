"""Release PR requirements come from the local, validated N1 inventory."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from _release_watch_facts import ReleaseFactsError, ReleaseFactsReader  # noqa: E402


class MasterGithub:
    def json(self, endpoint: str, **kwargs: Any) -> object:
        assert endpoint.endswith("git/ref/heads/master")
        return {"object": {"sha": "a" * 40}}

    def pages(self, endpoint: str, **kwargs: Any) -> list[object]:
        assert endpoint.endswith("actions/workflows/master-gate.yml/runs")
        return [{"workflow_runs": []}]


def test_master_records_local_inventory_without_branch_protection(
    tmp_path: Path,
) -> None:
    raw = (ROOT / ".github/release-qualification.json").read_bytes()
    inventory = json.loads(raw)
    # A distinct list proves the reader uses the configured checkout's bytes.
    inventory["merge_gate"]["required_checks"] = ["release-pr-smoke"]
    raw = json.dumps(inventory).encode()
    path = tmp_path / "inventory.json"
    path.write_bytes(raw)
    reader = ReleaseFactsReader(github=MasterGithub(), inventory_path=path)
    facts = reader._master_facts(datetime(2026, 11, 3, tzinfo=UTC))
    assert facts["expected_required_checks"] == [
        {"name": "release-pr-smoke", "source": "release-qualification inventory"}
    ]
    assert facts["expected_checks_readable"] is True
    assert facts["expected_checks_source"] == "release-qualification inventory"
    assert facts["inventory_digest"] == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("contents", [None, b"{", b"{}"])
def test_missing_or_malformed_inventory_is_unreadable(
    tmp_path: Path, contents: bytes | None
) -> None:
    path = tmp_path / "inventory.json"
    if contents is not None:
        path.write_bytes(contents)
    reader = ReleaseFactsReader(github=MasterGithub(), inventory_path=path)
    with pytest.raises(ReleaseFactsError, match="cannot read merge gate"):
        reader._master_facts(datetime(2026, 11, 3, tzinfo=UTC))
