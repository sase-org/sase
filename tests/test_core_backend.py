"""Tests for the sase.core backend selection helpers."""

from __future__ import annotations

import sys
import types

import pytest

from sase.core.backend import (
    BACKEND_ENV_VAR,
    DEFAULT_BACKEND,
    DUAL_RUN_ENV_VAR,
    RUST_EXTENSION_MODULE_NAME,
    Backend,
    RustBackendUnavailableError,
    dispatch,
    get_active_backend,
    is_dual_run_enabled,
    is_rust_available,
    load_rust_extension,
)


def test_default_backend_is_python(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BACKEND_ENV_VAR, raising=False)
    assert get_active_backend() is Backend.PYTHON
    assert DEFAULT_BACKEND is Backend.PYTHON


def test_explicit_python(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BACKEND_ENV_VAR, "python")
    assert get_active_backend() is Backend.PYTHON


def test_explicit_rust(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")
    assert get_active_backend() is Backend.RUST


def test_backend_env_var_is_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BACKEND_ENV_VAR, "  Rust  ")
    assert get_active_backend() is Backend.RUST


def test_unknown_backend_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BACKEND_ENV_VAR, "wasm")
    with pytest.raises(ValueError, match="wasm"):
        get_active_backend()


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", "TRUE"])
def test_dual_run_truthy(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(DUAL_RUN_ENV_VAR, value)
    assert is_dual_run_enabled() is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off"])
def test_dual_run_falsy(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(DUAL_RUN_ENV_VAR, value)
    assert is_dual_run_enabled() is False


def test_dual_run_unset_is_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DUAL_RUN_ENV_VAR, raising=False)
    assert is_dual_run_enabled() is False


def test_rust_unavailable_when_extension_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without ``sase_core_rs`` installed, the probe returns ``False``.

    The probe must swallow ``ImportError`` so a pure-Python install never
    breaks startup.
    """
    monkeypatch.delitem(sys.modules, RUST_EXTENSION_MODULE_NAME, raising=False)
    monkeypatch.setattr(
        "importlib.import_module",
        lambda name: (_ for _ in ()).throw(ImportError(f"No module named {name!r}")),
    )
    assert is_rust_available() is False
    assert load_rust_extension() is None


def test_rust_available_when_extension_importable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a fake ``sase_core_rs`` is registered, the probe returns ``True``."""
    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    monkeypatch.setitem(sys.modules, RUST_EXTENSION_MODULE_NAME, fake)
    assert is_rust_available() is True
    assert load_rust_extension() is fake


def test_dispatch_python_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BACKEND_ENV_VAR, raising=False)
    monkeypatch.delenv(DUAL_RUN_ENV_VAR, raising=False)

    def py(x: int, y: int) -> int:
        return x + y

    def rust(_x: int, _y: int) -> int:  # pragma: no cover - must not be called
        raise AssertionError("rust impl should not run on the python path")

    assert dispatch(operation="add", python_impl=py, rust_impl=rust, args=(2, 3)) == 5


def test_dispatch_rust_without_impl_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")

    def py() -> int:
        return 1

    with pytest.raises(RustBackendUnavailableError, match="Rust backend requested"):
        dispatch(operation="noop", python_impl=py)


def test_dispatch_rust_without_impl_can_fallback_to_python(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")

    def py(x: int) -> int:
        return x + 1

    assert (
        dispatch(
            operation="python_only",
            python_impl=py,
            rust_unavailable="python",
            args=(2,),
        )
        == 3
    )


def test_dispatch_rust_with_impl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")
    monkeypatch.delenv(DUAL_RUN_ENV_VAR, raising=False)

    def py() -> int:  # pragma: no cover - must not be called
        raise AssertionError("python impl should not run on the rust path")

    def rust() -> int:
        return 42

    assert dispatch(operation="answer", python_impl=py, rust_impl=rust) == 42
