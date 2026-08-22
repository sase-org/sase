from __future__ import annotations

from pathlib import Path
from types import ModuleType

import pytest

from tests import test_ratchet_core_window_tool as base


pytestmark = pytest.mark.contract


@pytest.fixture(scope="module")
def tool() -> ModuleType:
    return base._load_tool()


@pytest.mark.parametrize(
    ("before_source", "after_source"),
    [
        (
            'source = { registry = "https://pypi.org/simple/" }',
            'source = { registry = "https://pypi.org/simple" }',
        ),
        (
            'source = { registry = "https://pypi.org/simple" }',
            'source = { registry = "https://pypi.org/simple/" }',
        ),
    ],
)
def test_reconciliation_mode_allows_canonical_pypi_registry_spellings(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    before_source: str,
    after_source: str,
) -> None:
    pyproject, uv_lock = base._write_project_with_asttokens(
        tmp_path,
        asttokens_version="3.0.1",
        asttokens_source=before_source,
    )
    monkeypatch.setattr(
        tool,
        "fetch_pypi_metadata",
        lambda: base._metadata("0.21.3", "0.22.0"),
    )
    monkeypatch.setattr(
        tool,
        "_run_uv_lock",
        base._asttokens_refresh_lock_runner(
            tool,
            asttokens_version="3.0.1",
            asttokens_source=after_source,
        ),
    )

    code = tool.main(
        [
            "--allow-transitive-lock-refresh",
            "--pyproject",
            str(pyproject),
            "--uv-lock",
            str(uv_lock),
        ]
    )

    assert code == tool.EXIT_RATCHET
    lock_text = uv_lock.read_text(encoding="utf-8")
    assert 'name = "asttokens"\nversion = "3.0.1"' in lock_text
    assert after_source in lock_text
    out = capsys.readouterr().out
    assert "allowed transitive uv.lock refresh: asttokens 3.0.1" in out
    assert "applied" in out


@pytest.mark.parametrize(
    ("source", "diagnostic", "forbidden"),
    [
        (
            'source = { path = "vendor/asttokens" }',
            "source={path='vendor/asttokens'}",
            "",
        ),
        (
            'source = { git = "https://git.example/asttokens.git" }',
            "source={git='https://git.example/asttokens.git'}",
            "",
        ),
        (
            'source = { registry = "https://example.com/simple/" }',
            "source={registry='https://example.com/simple/'}",
            "",
        ),
        (
            'source = { registry = "https://user:secret@pypi.org/simple/" }',
            "source={registry='https://<credentials>@pypi.org/simple/'}",
            "secret",
        ),
        (
            'source = { registry = "https://pypi.org/simple/?mirror=1" }',
            "source={registry='https://pypi.org/simple/?mirror=1'}",
            "",
        ),
        (
            'source = { registry = "https://pypi.org/simple/#refresh" }',
            "source={registry='https://pypi.org/simple/#refresh'}",
            "",
        ),
        (
            'source = "https://pypi.org/simple/"',
            "source='https://pypi.org/simple/'",
            "",
        ),
        (
            'source = { registry = "https://pypi.org/simple/", extra = "field" }',
            "source={extra='field', registry='https://pypi.org/simple/'}",
            "",
        ),
    ],
)
def test_reconciliation_mode_rejects_ambiguous_transitive_sources(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    source: str,
    diagnostic: str,
    forbidden: str,
) -> None:
    pyproject, uv_lock = base._write_project_with_asttokens(tmp_path)
    before_pyproject = pyproject.read_text(encoding="utf-8")
    before_uv_lock = uv_lock.read_text(encoding="utf-8")
    monkeypatch.setattr(
        tool,
        "fetch_pypi_metadata",
        lambda: base._metadata("0.21.3", "0.22.0"),
    )
    monkeypatch.setattr(
        tool,
        "_run_uv_lock",
        base._asttokens_refresh_lock_runner(tool, asttokens_source=source),
    )

    code = tool.main(
        [
            "--allow-transitive-lock-refresh",
            "--pyproject",
            str(pyproject),
            "--uv-lock",
            str(uv_lock),
        ]
    )

    assert code == tool.EXIT_COULD_NOT_DETERMINE
    assert pyproject.read_text(encoding="utf-8") == before_pyproject
    assert uv_lock.read_text(encoding="utf-8") == before_uv_lock
    err = capsys.readouterr().err
    assert "is not a canonical PyPI registry package" in err
    assert diagnostic in err
    if forbidden:
        assert forbidden not in err
