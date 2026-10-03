"""Tests for the retired xprompt authored-surface doctor check."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.doctor import checks_config
from sase.doctor.checks_config_retired import (
    RETIRED_XPROMPT_NAMES_CHECK_ID,
    check_config_retired_xprompt_names,
)
from sase.doctor.runner import DoctorContext, default_doctor_context


def _doctor_context(tmp_path: Path, env: dict[str, str] | None = None) -> DoctorContext:
    return DoctorContext(cwd=tmp_path, project=None, sase_home=tmp_path, env=env or {})


def test_retired_names_check_is_registered() -> None:
    specs = checks_config.config_check_specs(default_doctor_context())
    spec_by_id = {spec.id: spec for spec in specs}

    assert RETIRED_XPROMPT_NAMES_CHECK_ID in spec_by_id
    assert spec_by_id[RETIRED_XPROMPT_NAMES_CHECK_ID].group == "config"


def test_retired_names_reports_env_without_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sase.config.core.load_config_layers", lambda: [])
    monkeypatch.setattr(
        "sase.content_layout.resolve_macro_file_sources", lambda **_k: ()
    )

    check = check_config_retired_xprompt_names(
        _doctor_context(tmp_path, env={"SASE_XPROMPT_LSP_CMD": "secret-cmd"})
    )

    assert check.id == "config.retired_xprompt_names"
    assert check.status == "WARN"
    assert any(
        finding["surface"] == "$SASE_XPROMPT_LSP_CMD is set"
        for finding in check.data["findings"]
    )
    assert "secret-cmd" not in str(check.details)
    assert "secret-cmd" not in str(check.data)


def test_retired_names_ok_on_clean_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib.metadata as importlib_metadata

    monkeypatch.setattr("sase.config.core.load_config_layers", lambda: [])
    monkeypatch.setattr(
        "sase.content_layout.resolve_macro_file_sources", lambda **_k: ()
    )
    monkeypatch.setattr(importlib_metadata, "entry_points", lambda: ())

    check = check_config_retired_xprompt_names(_doctor_context(tmp_path))

    assert check.status == "OK"
    assert list(check.data["findings"]) == []
