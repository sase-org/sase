"""Handler tests for ``sase var get`` selector query and path errors."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.main.var_get_helpers import run_var_get, seed_var_get_history


def test_get_path_and_no_match_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed_var_get_history(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        run_var_get(["build.status[0]", "--project", "gh_acme__widgets"])
    assert exc.value.code == 1
    assert "expected list, found string" in capsys.readouterr().err

    with pytest.raises(SystemExit) as exc:
        run_var_get(['build.report["nope"]', "--project", "gh_acme__widgets"])
    assert exc.value.code == 1
    assert "missing key" in capsys.readouterr().err

    with pytest.raises(SystemExit) as exc:
        run_var_get(["build.results[5]", "--project", "gh_acme__widgets"])
    assert exc.value.code == 1
    assert "out of range" in capsys.readouterr().err

    with pytest.raises(SystemExit) as exc:
        run_var_get(["missing.status"])
    assert exc.value.code == 1
    assert "no match for selector 'missing.status'" in capsys.readouterr().err


def test_get_raw_requires_one_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed_var_get_history(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        run_var_get(["*.status", "--format", "raw", "--limit", "0"])
    assert exc.value.code == 1
    assert "exactly one resolved value" in capsys.readouterr().err

    with pytest.raises(SystemExit) as exc:
        run_var_get(["*.status", "--format", "raw", "--limit", "1"])
    assert exc.value.code == 1
    assert "exactly one resolved value" in capsys.readouterr().err


def test_get_ambiguous_project_is_a_query_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seed_var_get_history(tmp_path, monkeypatch)

    with pytest.raises(SystemExit) as exc:
        run_var_get(["build.status", "--hidden"])
    assert exc.value.code == 1
    assert "multiple projects" in capsys.readouterr().err
