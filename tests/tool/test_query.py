from __future__ import annotations

from pathlib import Path

import pytest

from sase.tool.query import ToolShowCliRequest, handle_show


def test_show_missing_run_exits_2(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    code = handle_show(ToolShowCliRequest(run_id="missing-id", json=False, logs=False))
    captured = capsys.readouterr()
    assert code == 2
    assert "not found" in captured.err or "does not exist" in captured.err
