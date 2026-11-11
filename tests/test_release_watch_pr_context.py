"""Release-PR facts contract: pin_changed and stale_head (sase-1s7.7.1).

Collects the release-PR cases from
:mod:`tests._release_watch_facts_contract_cases` and adds the end-to-end
decision proof: a ready snapshot whose PR exact pin equals core-ensure's
pick but differs from master's exact pin reaches ``releasable`` with the
merge suppressed, instead of stopping at a metadata refresh.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from tests._release_steward_fixtures import releasable_request
from tests._release_watch_facts_contract_cases import (
    test_release_pr_pin_changed_ignores_exact_core_pin,
    test_release_pr_pin_changed_when_source_pins_differ,
    test_release_pr_stale_head_on_ahead_and_diverged,
)  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import _release_watch_decide as decide_tool  # noqa: E402


def _drifted_exact_request() -> dict[str, Any]:
    """Snapshot where only the exact core pin drifted past master.

    The PR pins ``0.44.2`` and core-ensure picks ``0.44.2``; master's exact
    pin is older. The fixed facts contract reports ``pin_changed`` False
    here because the source pins still match.
    """
    request = releasable_request()
    pr = request["snapshot"]["release_pr"]["value"]
    pr["exact_public_core_pin"] = "0.44.2"
    pr["pin_changed"] = False
    core_ensure = request["snapshot"]["core_ensure"]["value"]
    core_ensure["version"] = "0.44.2"
    core_ensure["files"] = [
        "sase_core_rs-0.44.2.tar.gz",
        "sase_core_rs-0.44.2-cp312-abi3-manylinux.whl",
    ]
    return request


def test_exact_pin_matching_core_ensure_pick_is_releasable() -> None:
    sase_core_rs = pytest.importorskip("sase_core_rs")
    if not hasattr(sase_core_rs, "release_steward_decide"):
        pytest.skip("installed sase_core_rs predates release_steward_decide")

    result = decide_tool.decide(_drifted_exact_request())
    assert result["primary"]["kind"] == "releasable"
    assert "metadata refresh" not in json.dumps(result)
    action = result["train_action"]
    assert action["action"]["kind"] == "merge_release_pr"
    # Observe-only ticks propose the merge without executing it.
    assert action["disposition"] == "proposed"
