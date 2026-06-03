"""Tests for indexed agent-name templates."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.names import (
    IndexedAgentNameNotFoundError,
    InvalidIndexedAgentNameTemplateError,
    allocate_indexed_agent_name,
    indexed_agent_name_base,
    is_concrete_indexed_agent_name_for_template,
    is_indexed_agent_name_template,
    latest_indexed_agent_name,
    require_latest_indexed_agent_name,
    resolve_indexed_agent_name_reference,
)

from tests._agent_names_fixtures import make_agent as _make_agent


def test_detects_only_terminal_indexed_marker() -> None:
    assert is_indexed_agent_name_template("build-@") is True
    assert is_indexed_agent_name_template("build-@-x") is False
    assert is_indexed_agent_name_template("build@") is False


def test_extracts_and_validates_template_base() -> None:
    assert indexed_agent_name_base("build-@") == "build"
    assert indexed_agent_name_base("build-stage-@") == "build-stage"

    with pytest.raises(InvalidIndexedAgentNameTemplateError, match="base"):
        indexed_agent_name_base("-@")
    with pytest.raises(InvalidIndexedAgentNameTemplateError, match="base"):
        indexed_agent_name_base("build--stage-@")
    with pytest.raises(InvalidIndexedAgentNameTemplateError, match="terminal"):
        indexed_agent_name_base("build-1")


def test_allocates_lowest_gap_and_mutates_reservation_set() -> None:
    reserved = {"build-1", "build-3"}

    assert allocate_indexed_agent_name("build-@", reserved=reserved) == "build-2"
    assert allocate_indexed_agent_name("build-@", reserved=reserved) == "build-4"
    assert reserved == {"build-1", "build-2", "build-3", "build-4"}


def test_latest_resolution_uses_highest_positive_integer() -> None:
    names = {
        "build",
        "build-0",
        "build-1",
        "build-09",
        "build-10",
        "build-2.child",
        "other-99",
    }

    assert latest_indexed_agent_name("build-@", names=names) == "build-10"


def test_latest_resolution_can_raise_typed_error() -> None:
    with pytest.raises(IndexedAgentNameNotFoundError, match="review-@"):
        require_latest_indexed_agent_name("review-@", names={"review", "review-0"})


def test_identifies_concrete_name_for_template() -> None:
    assert is_concrete_indexed_agent_name_for_template("build-1", "build-@") is True
    assert is_concrete_indexed_agent_name_for_template("build-01", "build-@") is False
    assert is_concrete_indexed_agent_name_for_template("other-1", "build-@") is False
    assert (
        is_concrete_indexed_agent_name_for_template("build-1.child", "build-@") is False
    )


def test_registry_backed_reservations(tmp_path: Path) -> None:
    _make_agent(tmp_path, "proj", "run1", "build-1")
    _make_agent(tmp_path, "proj", "run2", "build-3")

    with patch.object(Path, "home", return_value=tmp_path):
        assert allocate_indexed_agent_name("build-@") == "build-2"
        assert latest_indexed_agent_name("build-@") == "build-3"
        assert resolve_indexed_agent_name_reference("plain") == "plain"
        assert resolve_indexed_agent_name_reference("build-@") == "build-3"
