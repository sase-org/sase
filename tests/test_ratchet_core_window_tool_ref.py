"""Read-only ``--ref`` / ``--fetch`` tests for ratchet_core_pin."""

from __future__ import annotations

from types import ModuleType

import pytest

from tests._ratchet_core_window_tool_helpers import SOURCE_PIN
from tests._ratchet_core_window_tool_helpers import fake_core_lag as _fake_core_lag
from tests._ratchet_core_window_tool_helpers import fake_ensure as _fake_ensure
from tests._ratchet_core_window_tool_helpers import load_tool as _load_tool
from tests._ratchet_core_window_tool_helpers import lock_text as _lock_text
from tests._ratchet_core_window_tool_helpers import pyproject_text as _pyproject_text


pytestmark = pytest.mark.contract


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    return _load_tool()


def _install_ref_files(
    tool: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    *,
    specifier: str = "==0.21.3",
    lock_version: str = "0.21.3",
    pin: str = SOURCE_PIN,
) -> list[tuple[str, str]]:
    shown: list[tuple[str, str]] = []
    files = {
        "pyproject.toml": _pyproject_text(specifier),
        "uv.lock": _lock_text(lock_version, specifier),
        "sase-core-revision.txt": f"{pin}\n",
    }

    def _git_show(ref: str, relative_path: str) -> str:
        shown.append((ref, relative_path))
        try:
            return files[relative_path]
        except KeyError as exc:
            raise tool.RatchetError(
                f"git show {ref}:{relative_path} failed: path not in fixture"
            ) from exc

    monkeypatch.setattr(tool, "_git_show", _git_show)
    return shown


def test_check_ref_published_pin_exits_ok(
    tool: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    shown = _install_ref_files(tool, monkeypatch)
    monkeypatch.setattr(tool, "ensure_core", _fake_ensure(tool, "0.21.3"))
    fetch_calls = 0

    def _fetch() -> None:
        nonlocal fetch_calls
        fetch_calls += 1

    monkeypatch.setattr(tool, "_fetch_origin", _fetch)

    code = tool.main(["--check", "--fetch", "--ref", "origin/master"])

    assert code == tool.EXIT_OK
    assert fetch_calls == 1
    assert shown == [
        ("origin/master", "pyproject.toml"),
        ("origin/master", "uv.lock"),
        ("origin/master", "sase-core-revision.txt"),
    ]
    assert "PINNED(0.21.3, files=" in capsys.readouterr().out


def test_check_ref_unpublished_pin_is_core_lag(
    tool: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_ref_files(tool, monkeypatch)
    monkeypatch.setattr(tool, "ensure_core", _fake_core_lag(tool))

    def _unexpected_fetch() -> None:
        raise AssertionError("check --ref without --fetch must not fetch origin")

    monkeypatch.setattr(tool, "_fetch_origin", _unexpected_fetch)

    code = tool.main(["--check", "--ref", "origin/master"])

    assert code == tool.EXIT_COULD_NOT_DETERMINE
    captured = capsys.readouterr()
    assert "CORE_LAG(pin=" in captured.out
    assert "newest_complete=0.42.1" in captured.out


def test_ref_without_check_or_report_only_is_refused(
    tool: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _unexpected_show(_ref: str, _relative_path: str) -> str:
        raise AssertionError("--ref apply must not read git blobs")

    def _unexpected_fetch() -> None:
        raise AssertionError("--ref apply must not fetch origin")

    monkeypatch.setattr(tool, "_git_show", _unexpected_show)
    monkeypatch.setattr(tool, "_fetch_origin", _unexpected_fetch)

    code = tool.main(["--ref", "origin/master"])

    assert code == tool.EXIT_COULD_NOT_DETERMINE
    assert "--ref is read-only" in capsys.readouterr().err


def test_fetch_failure_exits_could_not_determine(
    tool: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _fail_fetch() -> None:
        raise tool.RatchetError("git fetch origin failed: connection refused")

    def _unexpected_show(_ref: str, _relative_path: str) -> str:
        raise AssertionError("fetch failure must not read git blobs")

    monkeypatch.setattr(tool, "_fetch_origin", _fail_fetch)
    monkeypatch.setattr(tool, "_git_show", _unexpected_show)

    code = tool.main(["--check", "--fetch", "--ref", "origin/master"])

    assert code == tool.EXIT_COULD_NOT_DETERMINE
    assert "git fetch origin failed: connection refused" in capsys.readouterr().err
