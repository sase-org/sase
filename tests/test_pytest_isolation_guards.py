"""Guard pytest home isolation against undo-able patches."""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TESTS_ROOT = _REPO_ROOT / "tests"
_THIS_FILE = str(Path(__file__).resolve())


def _undo_on_injected_monkeypatch(tree: ast.AST) -> list[str]:
    """Return ``file:line`` hits calling ``monkeypatch.undo()`` on the fixture."""
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        arg_names = {arg.arg for arg in node.args.args}
        arg_names.update(arg.arg for arg in node.args.posonlyargs)
        arg_names.update(arg.arg for arg in node.args.kwonlyargs)
        if node.args.vararg is not None:
            arg_names.add(node.args.vararg.arg)
        if node.args.kwarg is not None:
            arg_names.add(node.args.kwarg.arg)
        if "monkeypatch" not in arg_names:
            continue
        for child in ast.walk(node):
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == "undo"
                and isinstance(child.func.value, ast.Name)
                and child.func.value.id == "monkeypatch"
            ):
                hits.append(f"{node.lineno}:{child.lineno}")
    return hits


def test_no_undo_on_shared_monkeypatch_fixture() -> None:
    """Fail when `.undo()` is called on the injected `monkeypatch` fixture.

    Locally constructed `pytest.MonkeyPatch()` instances stay allowed; only
    the function or fixture parameter named `monkeypatch` is guarded. Use
    `monkeypatch.context()` for scoped patches instead.
    """
    offenders: list[str] = []
    for path in sorted(_TESTS_ROOT.rglob("*.py")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if ".undo()" not in text or "monkeypatch" not in text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for hit in _undo_on_injected_monkeypatch(tree):
            _def_line, call_line = hit.split(":")
            offenders.append(f"{path.relative_to(_REPO_ROOT)}:{call_line}")
    assert not offenders, (
        "monkeypatch.undo() on the shared fixture drops home isolation; "
        "use monkeypatch.context() instead: " + ", ".join(offenders)
    )


@pytest.fixture(scope="module")
def _module_home_baseline() -> tuple[str | None, str | None]:
    """Capture the HOME/SASE_HOME fallback a module-scoped fixture sees.

    A module-scoped fixture runs after the session fixtures and before the
    function-level isolation, so it sees exactly what an undo of the
    function-level patches reverts to.
    """
    return (os.environ.get("HOME"), os.environ.get("SASE_HOME"))


def test_session_sandbox_seals_home_after_function_patches_lost(
    monkeypatch: pytest.MonkeyPatch,
    _module_home_baseline: tuple[str | None, str | None],
) -> None:
    """Losing function-level patches still lands inside the pytest sandbox."""
    from sase.core import paths as _paths
    from sase.core.state_write_guard import _account_home

    sandbox = Path(os.environ["SASE_PYTEST_SANDBOX_DIR"]).resolve()
    account_home = _account_home().resolve()
    real_state_root = (account_home / ".sase").resolve()

    baseline_home, baseline_sase_home = _module_home_baseline
    for label, baseline in (("HOME", baseline_home), ("SASE_HOME", baseline_sase_home)):
        assert baseline is not None, f"module baseline {label} is unexpectedly None"
        resolved = Path(baseline).expanduser().resolve(strict=False)
        assert resolved == sandbox or sandbox in resolved.parents, (
            f"module baseline {label}={baseline} escapes sandbox {sandbox}"
        )

    # Simulate losing the per-test env keys inside a scoped context: fall
    # back to the module baseline, never the account home.
    with monkeypatch.context() as scoped:
        if baseline_home is None:
            scoped.delenv("HOME", raising=False)
        else:
            scoped.setenv("HOME", baseline_home)
        if baseline_sase_home is None:
            scoped.delenv("SASE_HOME", raising=False)
        else:
            scoped.setenv("SASE_HOME", baseline_sase_home)
        fallback = _paths.sase_home().expanduser().resolve(strict=False)
        assert fallback == sandbox or sandbox in fallback.parents, (
            f"post-undo sase_home() {fallback} escapes sandbox {sandbox}"
        )
        assert fallback != real_state_root
        assert (
            real_state_root not in fallback.parents
            or sandbox in real_state_root.parents
        )


def test_session_sandbox_seal_is_not_first_test(
    pytester: pytest.Pytester,
) -> None:
    """Guarantee the seal test never runs as a worker's first test."""
    result = pytester.runpytest_subprocess(
        "-p",
        "no:randomly",
        "-c",
        str(_REPO_ROOT / "pyproject.toml"),
        "--rootdir",
        str(_REPO_ROOT),
        f"{_THIS_FILE}::test_no_undo_on_shared_monkeypatch_fixture",
        f"{_THIS_FILE}::test_session_sandbox_seals_home_after_function_patches_lost",
        timeout=60,
    )
    result.assert_outcomes(passed=2)
