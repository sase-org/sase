"""Tests for gate-time frozen Decision Sheet writes."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from sase.sdd.plan_decision_freeze import (
    read_frozen_definitions,
    sibling_path_for_plan,
    write_gate_frozen_definitions,
)

_UNSTAMPED = """---
tier: tale
title: Unstamped freeze
goal: Cover gate-time freeze writes.
size: small
---
# Plan

Body.
"""

_STAMPED = """---
tier: tale
title: Stamped freeze
goal: Cover accepted freeze immutability.
size: small
decided_by: reviewer
decided_via: tui
---
# Plan

Body.
"""


def test_write_gate_frozen_definitions_round_trips(tmp_path: Path) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text(_UNSTAMPED, encoding="utf-8")
    definitions = [{"id": "grouping", "kind": "choice", "default": "pane"}]

    assert write_gate_frozen_definitions(plan, definitions) is True
    assert read_frozen_definitions(plan) == definitions
    sibling = sibling_path_for_plan(plan)
    payload = json.loads(sibling.read_text(encoding="utf-8"))
    assert payload["schema"] == 1
    assert payload["definitions"] == definitions


def test_write_gate_frozen_definitions_overwrites_stale_sibling(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text(_UNSTAMPED, encoding="utf-8")
    sibling = sibling_path_for_plan(plan)
    sibling.write_text(
        json.dumps({"schema": 1, "definitions": [{"id": "old"}]}, indent=2) + "\n",
        encoding="utf-8",
    )

    assert write_gate_frozen_definitions(plan, [{"id": "new"}]) is True
    assert read_frozen_definitions(plan) == [{"id": "new"}]


def test_write_gate_frozen_definitions_leaves_stamped_sibling(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text(_STAMPED, encoding="utf-8")
    sibling = sibling_path_for_plan(plan)
    sentinel = json.dumps({"schema": 1, "definitions": [{"id": "kept"}]}) + "\n"
    sibling.write_text(sentinel, encoding="utf-8")

    assert write_gate_frozen_definitions(plan, [{"id": "new"}]) is False
    assert sibling.read_text(encoding="utf-8") == sentinel


def test_write_gate_frozen_definitions_empty_returns_false(tmp_path: Path) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text(_UNSTAMPED, encoding="utf-8")

    assert write_gate_frozen_definitions(plan, []) is False
    assert write_gate_frozen_definitions(plan, None) is False
    assert not sibling_path_for_plan(plan).exists()


def test_write_gate_frozen_definitions_leaves_no_temp_files(tmp_path: Path) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text(_UNSTAMPED, encoding="utf-8")

    assert write_gate_frozen_definitions(plan, [{"id": "grouping"}]) is True
    names = {path.name for path in tmp_path.iterdir()}
    assert names == {plan.name, sibling_path_for_plan(plan).name}


def test_write_gate_frozen_definitions_failed_replace_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text(_UNSTAMPED, encoding="utf-8")

    def boom(_src: object, _dst: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", boom)
    assert write_gate_frozen_definitions(plan, [{"id": "grouping"}]) is False
    leftovers = [path.name for path in tmp_path.iterdir() if path.name != plan.name]
    assert leftovers == []
