"""Tests for the BackendIndicator widget rendering."""

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.backend_indicator import BackendIndicator
from sase.core.backend import (
    BACKEND_ENV_VAR,
    DUAL_RUN_ENV_VAR,
    BackendDisplay,
)


def test_backend_indicator_renders_rust_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(BACKEND_ENV_VAR, raising=False)
    monkeypatch.delenv(DUAL_RUN_ENV_VAR, raising=False)

    text = BackendIndicator._build_content()

    assert text.plain == " backend: Rust "
    assert "#90BE6D" in str(text.style)


def test_backend_indicator_renders_python_when_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(BACKEND_ENV_VAR, "python")
    monkeypatch.delenv(DUAL_RUN_ENV_VAR, raising=False)

    text = BackendIndicator._build_content()

    assert text.plain == " backend: Python "
    assert "#A9D6E5" in str(text.style)


def test_backend_indicator_renders_dual_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BACKEND_ENV_VAR, "python")
    monkeypatch.setenv(DUAL_RUN_ENV_VAR, "1")

    text = BackendIndicator._build_content()

    assert text.plain == " backend: Python+Rust dual "
    assert "#CDB4DB" in str(text.style)


def test_backend_indicator_accepts_display_descriptor() -> None:
    text = BackendIndicator._build_content(
        BackendDisplay(label="backend: Test", style="bold red")
    )

    assert text.plain == " backend: Test "
    assert "red" in str(text.style)


async def test_backend_indicator_is_mounted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BACKEND_ENV_VAR, raising=False)
    monkeypatch.delenv(DUAL_RUN_ENV_VAR, raising=False)

    async with AcePage() as page:
        indicator = page.query_one_widget("#backend-indicator", BackendIndicator)

    assert isinstance(indicator, BackendIndicator)
