"""A read-only bead command in an unmanaged repo must fail cleanly, not traceback."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from sase.main.entry import main as sase_main
from tests.sdd_policy_helpers import set_sdd_policy


def test_bead_list_in_unmanaged_repo_exits_cleanly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`sase bead list` in a repo lacking `is_sase_managed: true` must print one
    actionable line to stderr and exit 1, never a Python traceback."""
    primary = tmp_path / "repo"
    primary.mkdir()
    monkeypatch.chdir(primary)
    monkeypatch.setattr(sys, "argv", ["sase", "bead", "list"])
    monkeypatch.setattr(
        "sase.bead.workspace.resolve_primary_workspace",
        lambda: primary,
    )
    set_sdd_policy(monkeypatch, "separate_repo")

    with pytest.raises(SystemExit) as excinfo:
        sase_main()

    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert err.count("SDD materialization refused") == 1
    assert "is_sase_managed: true" in err
    assert "Traceback" not in err
