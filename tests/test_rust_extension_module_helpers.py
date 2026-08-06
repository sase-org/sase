"""Regression tests for the shared ``sase_core_rs`` ``sys.modules`` helpers.

These pin the invariant the six extension-patching test modules kept
breaking: a test may swap or evict the extension package, but it must not
leave the compiled submodule cached behind an absent parent. When it does,
re-executing the package init raises
``NameError: name 'sase_core_rs' is not defined`` and every later import in
that process fails — under pytest-xdist, that means every later test
scheduled onto the poisoned worker.

The assertions target the *helpers'* contract (parent and submodule move as
a unit), not the wheel's own robustness, so they hold both against the
current maturin star-import init and against a hardened one.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import types

import pytest

from sase.core.rust import RUST_EXTENSION_MODULE_NAME

from ._rust_extension_module_helpers import (
    RUST_EXTENSION_SUBMODULE_NAME,
    evict_rust_extension,
    install_fake_rust_extension,
    patch_rust_extension,
)

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec(RUST_EXTENSION_MODULE_NAME) is None,
    reason="sase_core_rs is required to exercise the re-import invariant.",
)


def test_patch_rust_extension_evicts_the_compiled_submodule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Swapping the parent must not leave the compiled submodule cached."""
    importlib.import_module(RUST_EXTENSION_MODULE_NAME)

    fake = types.ModuleType(RUST_EXTENSION_MODULE_NAME)
    assert patch_rust_extension(monkeypatch, fake) is fake

    assert sys.modules[RUST_EXTENSION_MODULE_NAME] is fake
    assert RUST_EXTENSION_SUBMODULE_NAME not in sys.modules


def test_evict_rust_extension_evicts_the_compiled_submodule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    importlib.import_module(RUST_EXTENSION_MODULE_NAME)

    evict_rust_extension(monkeypatch)

    assert RUST_EXTENSION_MODULE_NAME not in sys.modules
    assert RUST_EXTENSION_SUBMODULE_NAME not in sys.modules


def test_reimport_while_patched_does_not_poison_the_process() -> None:
    """A re-import behind the helper's patch rebinds the extension name.

    This is the exact sequence the old ``monkeypatch.setitem`` pattern got
    wrong: with the submodule still cached, re-executing the package init
    raised ``NameError`` and broke every later import.
    """
    importlib.import_module(RUST_EXTENSION_MODULE_NAME)

    with pytest.MonkeyPatch.context() as patched:
        install_fake_rust_extension(patched)
        del sys.modules[RUST_EXTENSION_MODULE_NAME]
        module = importlib.import_module(RUST_EXTENSION_MODULE_NAME)
        assert getattr(module, RUST_EXTENSION_MODULE_NAME, None) is not None

    _assert_extension_is_importable()


def test_extension_is_importable_after_evict_teardown() -> None:
    """After the helper's teardown the real extension still imports."""
    importlib.import_module(RUST_EXTENSION_MODULE_NAME)

    with pytest.MonkeyPatch.context() as patched:
        evict_rust_extension(patched)
        assert RUST_EXTENSION_MODULE_NAME not in sys.modules

    _assert_extension_is_importable()


def _assert_extension_is_importable() -> None:
    module = importlib.import_module(RUST_EXTENSION_MODULE_NAME)
    submodule = getattr(module, RUST_EXTENSION_MODULE_NAME, None)
    assert submodule is not None, (
        f"{RUST_EXTENSION_MODULE_NAME} re-imported without binding its "
        "compiled submodule; the process is poisoned for every later import"
    )
    assert sys.modules[RUST_EXTENSION_SUBMODULE_NAME] is submodule
