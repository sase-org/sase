"""Dogfood tests for the bundled `#pr` status enum."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.macro.input_binding import InputBindingError, bind_input_args
from sase.macro.models import InputType
from sase.macro.workflow_loader import _load_workflow_from_file

_PR_YML = Path(__file__).resolve().parents[1] / "src" / "sase" / "macros" / "pr.yml"


def _pr_inputs() -> list:
    workflow = _load_workflow_from_file(_PR_YML)
    assert workflow is not None
    return [input_arg for input_arg in workflow.inputs if not input_arg.is_step_input]


def test_pr_status_is_enum_with_wip_draft_ready() -> None:
    status = next(input_arg for input_arg in _pr_inputs() if input_arg.name == "status")
    assert status.type is InputType.ENUM
    assert status.default == "draft"
    assert tuple(choice.value for choice in status.choices) == ("wip", "draft", "ready")


def test_pr_named_ready_status_binds() -> None:
    bound = bind_input_args(_pr_inputs(), ["x"], {"status": "ready"})
    assert bound.values["name"] == "x"
    assert bound.values["status"] == "ready"


def test_pr_title_case_status_suggests_ready() -> None:
    with pytest.raises(InputBindingError, match="did you mean `ready`") as excinfo:
        bind_input_args(_pr_inputs(), ["x"], {"status": "Ready"})
    assert "ready" in str(excinfo.value)


def test_pr_colon_ready_binds_name_not_status() -> None:
    bound = bind_input_args(_pr_inputs(), ["ready"], {})
    assert bound.values["name"] == "ready"
    assert bound.values["status"] == "draft"
