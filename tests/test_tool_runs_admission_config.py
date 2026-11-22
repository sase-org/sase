"""``tool_runs.admission`` parsing, validation, and defaults."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sase.config.core import clear_config_cache
from sase.config.tool_admission import (
    DEFAULT_TOOL_RUNS_ADMISSION_MAX_WAIT_SECONDS,
    get_tool_runs_admission_config,
    _parse_tool_runs_admission,
)
from sase.config.tools import ToolRunsConfigError, get_tool_runs_config


def _project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool_runs: object
) -> None:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    (root / "sase").mkdir()
    (root / "sase" / "sase.yml").write_text(
        yaml.safe_dump({"tool_runs": tool_runs}), encoding="utf-8"
    )
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    monkeypatch.chdir(root)
    clear_config_cache()


def test_absent_section_is_unlimited() -> None:
    policy = _parse_tool_runs_admission(None)
    assert dict(policy.max_concurrent) == {}
    assert policy.max_wait_seconds == DEFAULT_TOOL_RUNS_ADMISSION_MAX_WAIT_SECONDS
    assert policy.limit_for("check") is None
    assert policy.limit_for(None) is None


def test_valid_section_parses_limits_and_max_wait() -> None:
    policy = _parse_tool_runs_admission(
        {"max_concurrent": {"check": 3, "test": 1}, "max_wait_seconds": 0}
    )
    assert policy.limit_for("check") == 3
    assert policy.limit_for("test") == 1
    assert policy.limit_for("lint") is None
    assert policy.max_wait_seconds == 0


@pytest.mark.parametrize(
    ("section", "message"),
    [
        ("check", "tool_runs.admission must be a mapping"),
        ({"max_concurent": {}}, "unknown tool_runs.admission field(s): max_concurent"),
        ({"max_concurrent": [1]}, "tool_runs.admission.max_concurrent must be"),
        ({"max_concurrent": {"check": 0}}, "max_concurrent.check must be an integer"),
        ({"max_concurrent": {"check": True}}, "max_concurrent.check must be"),
        ({"max_concurrent": {"check": "3"}}, "max_concurrent.check must be"),
        ({"max_concurrent": {"": 2}}, "keys must be nonempty tool names"),
        ({"max_wait_seconds": -1}, "max_wait_seconds must be an integer >= 0"),
        ({"max_wait_seconds": 1.5}, "max_wait_seconds must be an integer >= 0"),
        ({"max_wait_seconds": False}, "max_wait_seconds must be an integer >= 0"),
    ],
)
def test_invalid_sections_name_the_field(section: object, message: str) -> None:
    with pytest.raises(ToolRunsConfigError) as raised:
        _parse_tool_runs_admission(section)
    assert message in str(raised.value)


def test_merged_config_defaults_are_unlimited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project(tmp_path, monkeypatch, {})
    policy = get_tool_runs_admission_config()
    assert dict(policy.max_concurrent) == {}
    assert policy.max_wait_seconds == 3600


def test_merged_config_reads_a_layer_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project(
        tmp_path,
        monkeypatch,
        {"admission": {"max_concurrent": {"check": 2}, "max_wait_seconds": 60}},
    )
    policy = get_tool_runs_admission_config()
    assert policy.limit_for("check") == 2
    assert policy.max_wait_seconds == 60
    # Retention policy accepts the new field instead of rejecting it as unknown.
    assert get_tool_runs_config()["summary_days"] >= 1
