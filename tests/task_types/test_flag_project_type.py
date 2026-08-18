"""The project-local ``flag`` task type declared in ``sase/sase.yml``."""

from __future__ import annotations

import pytest

from sase.task_types import TaskTypeCreateError, resolve_created_task_type
from sase.task_types._models import TaskTypeRecord
from sase.task_types._validation import validate_task_type_spec
from sase.task_types.registry import get_task_type_registry


_EXPECTED_FIELDS = (
    "key",
    "kind",
    "when_enabled",
    "when_disabled",
    "remove_when",
    "remove_by_date",
    "remove_by_release",
)


def _flag_record() -> TaskTypeRecord:
    record = get_task_type_registry().by_slug.get("flag")
    assert record is not None, "flag task type missing from the live catalog"
    return record


def test_flag_project_type_is_in_the_live_catalog() -> None:
    record = _flag_record()
    spec = record.spec

    assert record.provenance.source == "project"
    assert record.provenance.package == "sase"
    assert record.agent_creatable is False
    assert spec["label"] == "Feature flag"
    assert spec["glyph"] == "⚑"
    assert spec["accent_color"] == "#FF875F"
    assert "\n" not in spec["summary"]
    assert len(spec["summary"]) <= 120
    assert len(spec["when_to_use"]) <= 400
    assert "sase flag new" in spec["when_to_use"]
    assert tuple(field["name"] for field in spec["fields"]) == _EXPECTED_FIELDS
    assert spec["fields"][0]["pattern"] == r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$"
    assert spec["fields"][1]["values"] == ["beta", "sunset"]
    assert spec["fields"][5]["type"] == "date"
    assert spec["fields"][5]["role"] == ["data"]
    assert spec["fields"][6]["role"] == ["data"]
    assert spec["fields"][6]["pattern"] == r"^[0-9]+\.[0-9]+\.[0-9]+$"
    assert "{{ when_enabled }}" in spec["body_template"]
    assert spec["triage"]["min_plus_ones"] == 0
    assert len(validate_task_type_spec(spec)) == 64


def test_flag_cannot_be_created_through_bead_create() -> None:
    record = _flag_record()

    with pytest.raises(
        TaskTypeCreateError, match="cannot be created by agents"
    ) as exc_info:
        resolve_created_task_type("flag", {}, registry=get_task_type_registry())

    message = str(exc_info.value)
    assert "sase flag new" in message
    assert record.spec["when_to_use"] in message
    assert "reserved for the providing plugin" not in message
