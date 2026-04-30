"""Backend contract audit tests for ``sase.core`` facade dispatch (Phase 6C).

Phase 6C audits every ``dispatch(...)`` call site under ``src/sase/core/`` and
classifies it as either:

- **shipped** — a Rust binding is registered when ``sase_core_rs`` exposes the
  matching attribute. Under ``SASE_CORE_BACKEND=rust`` a missing/stale binding
  must raise :class:`RustBackendUnavailableError` instead of falling back to
  Python; and
- **unported** — the facade explicitly opts into Python with
  ``rust_unavailable="python"``, so Rust mode keeps running Python without an
  error.

These tests pin the contract at the dispatcher level so the Phase 6F default
flip cannot discover that a facade silently masked a missing shipped binding
(the failure mode Phase 6C was meant to prevent and Phase 6F now relies on).

The per-facade tests under ``tests/test_core_facade/test_*.py`` and
``tests/test_core_git_query.py`` /
``tests/test_core_agent_scan.py`` already cover the Rust-routing happy paths;
this file is the cross-cutting audit that enumerates the full set in one place.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.core.backend import (
    BACKEND_ENV_VAR,
    DEFAULT_BACKEND,
    DUAL_RUN_ENV_VAR,
    RUST_EXTENSION_MODULE_NAME,
    Backend,
    RustBackendUnavailableError,
    dispatch,
)
from sase.core.dual_run import DUAL_RUN_LOG_OVERRIDE_ENV_VAR


# Phase 8D rewired ``parse_project_bytes``, ``parse_query``, and
# ``scan_agent_artifacts`` to call ``sase_core_rs`` directly through
# :mod:`sase.core.rust`. Phase 8E followed by direct-wiring the status
# (``read_status_from_lines``, ``apply_status_update``,
# ``plan_status_transition``) and Git query (``parse_git_name_status_z``,
# ``parse_git_branch_name``, ``derive_git_workspace_name``,
# ``parse_git_conflicted_files``, ``parse_git_local_changes``) helpers.
# After both phases land, no shipped operation flows through
# ``dispatch(...)`` and the list is empty. Per-facade tests under
# ``tests/test_core_facade/test_parser.py``,
# ``tests/test_core_facade/test_query.py``,
# ``tests/test_core_agent_scan.py``,
# ``tests/test_core_facade/test_status.py``, and
# ``tests/test_core_git_query.py`` pin the direct-Rust contract instead.
SHIPPED_OPERATIONS: tuple[str, ...] = ()


# Operations that intentionally route through Python via the dispatcher's
# ``rust_unavailable="python"`` opt-in. Phase 8C rewired all previously
# unported facades (build_query_context, evaluate_query,
# evaluate_query_with_context, build_changespec_graph_index, and
# Phase 8B's deferred evaluate_query_many) to call their Python
# implementations directly without consulting the dispatcher.  Phase 8E
# also pulled transition_changespec_status off the dispatcher (now a
# direct call into transition_changespec_status_python documented as
# host logic), and direct-wired the status / Git query helpers
# (read_status_from_lines, apply_status_update, plan_status_transition,
# parse_git_name_status_z, parse_git_branch_name,
# derive_git_workspace_name, parse_git_conflicted_files,
# parse_git_local_changes) to ``sase_core_rs`` via
# :func:`sase.core.rust.require_rust_binding`. The list is therefore
# empty; Phase 8F deletes the dispatcher entirely and retires this audit.
UNPORTED_OPERATIONS: tuple[str, ...] = ()


def test_default_backend_is_rust(monkeypatch: pytest.MonkeyPatch) -> None:
    """Phase 6F flipped the default; the contract assertion follows suit."""
    monkeypatch.delenv(BACKEND_ENV_VAR, raising=False)
    assert DEFAULT_BACKEND is Backend.RUST


@pytest.mark.parametrize("operation", SHIPPED_OPERATIONS)
def test_shipped_dispatch_raises_when_rust_binding_missing(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """Every shipped operation surfaces a clean error when no Rust impl exists.

    Mirrors the runtime contract: under ``SASE_CORE_BACKEND=rust`` the
    facade may *not* silently fall through to Python for a shipped binding;
    the dispatcher is the single point of failure that proves it.
    """
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")

    def python_impl() -> object:  # pragma: no cover - must not run under rust
        raise AssertionError(
            f"python_impl should not run for shipped op {operation!r} under rust mode"
        )

    with pytest.raises(RustBackendUnavailableError) as excinfo:
        dispatch(operation=operation, python_impl=python_impl)
    message = str(excinfo.value)
    assert operation in message, (
        f"Error text for {operation!r} should name the operation; got: {message!r}"
    )
    assert RUST_EXTENSION_MODULE_NAME in message, (
        f"Error text for {operation!r} should name the {RUST_EXTENSION_MODULE_NAME} "
        f"extension; got: {message!r}"
    )
    assert f"{BACKEND_ENV_VAR}=python" in message, (
        f"Error text for {operation!r} should name the "
        f"{BACKEND_ENV_VAR}=python escape hatch; got: {message!r}"
    )


@pytest.mark.parametrize("operation", UNPORTED_OPERATIONS)
def test_unported_dispatch_falls_back_to_python_under_rust(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """Unported operations stay on Python under ``SASE_CORE_BACKEND=rust``.

    The contract is that ``rust_unavailable="python"`` is the only way for a
    dispatched operation to reach the Python implementation under Rust mode.
    """
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")
    sentinel = object()

    def python_impl() -> object:
        return sentinel

    result = dispatch(
        operation=operation,
        python_impl=python_impl,
        rust_unavailable="python",
    )
    assert result is sentinel


def test_dispatch_dual_run_is_noop_without_rust_impl(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Dual-run logs nothing when the dispatched operation has no ``rust_impl``.

    Unported facade APIs (graph index, query context/per-row, etc.) declare
    no ``rust_impl``. ``SASE_CORE_DUAL_RUN=1`` must therefore be a no-op for
    them — the Python implementation runs once, no comparison record is
    written, and TUI/CLI behavior is identical to the non-dual-run path.
    """
    log_path = tmp_path / "core_dual_run.jsonl"
    monkeypatch.setenv(DUAL_RUN_LOG_OVERRIDE_ENV_VAR, str(log_path))
    monkeypatch.setenv(DUAL_RUN_ENV_VAR, "1")
    # Pin to explicit Python: under default Rust the missing rust_impl
    # would raise before reaching the dual-run branch, which is not what
    # this test exercises. The dual-run no-op-without-rust_impl contract
    # is backend-agnostic; explicit Python is the simplest way to drive it.
    monkeypatch.setenv(BACKEND_ENV_VAR, "python")

    calls: list[int] = []

    def python_impl() -> int:
        calls.append(1)
        return 7

    result = dispatch(operation="unported_dual_run_check", python_impl=python_impl)
    assert result == 7
    assert calls == [1]
    assert not log_path.exists() or log_path.read_text() == "", (
        "dual-run must not write a record for an operation with no rust_impl"
    )


def test_unported_python_fallback_dual_run_is_also_noop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Unported ``rust_unavailable='python'`` ops do not generate dual-run records.

    Under ``SASE_CORE_DUAL_RUN=1`` with no ``rust_impl``, neither the Rust
    branch nor the comparison path executes, so no JSONL record is appended.
    This pins the side-effect contract for ``transition_changespec_status``
    and the other Python-only entry points.
    """
    log_path = tmp_path / "core_dual_run.jsonl"
    monkeypatch.setenv(DUAL_RUN_LOG_OVERRIDE_ENV_VAR, str(log_path))
    monkeypatch.setenv(DUAL_RUN_ENV_VAR, "1")
    monkeypatch.setenv(BACKEND_ENV_VAR, "rust")

    calls: list[int] = []

    def python_impl() -> int:
        calls.append(1)
        return 11

    result = dispatch(
        operation="unported_rust_python_fallback",
        python_impl=python_impl,
        rust_unavailable="python",
    )
    assert result == 11
    assert calls == [1]
    assert not log_path.exists() or log_path.read_text() == ""


def test_facade_inventory_matches_expected_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catch silent reclassification by import-walking every facade module.

    If a future patch adds a new ``dispatch(operation=...)`` call site, this
    test will fail until the new operation is explicitly added to
    :data:`SHIPPED_OPERATIONS` or :data:`UNPORTED_OPERATIONS` (or the
    operation-name extraction is adapted). This keeps the contract audit in
    sync with the actual facade surface.
    """
    monkeypatch.delenv(BACKEND_ENV_VAR, raising=False)
    facade_root = Path(__file__).resolve().parents[2] / "src" / "sase" / "core"
    operations: set[str] = set()
    for path in sorted(facade_root.glob("*_facade.py")):
        text = path.read_text()
        # Each dispatch() call passes ``operation="<name>"`` as a literal
        # keyword argument. Extract those names with a tolerant string scan.
        for chunk in text.split('operation="')[1:]:
            end = chunk.find('"')
            if end != -1:
                operations.add(chunk[:end])

    classified = set(SHIPPED_OPERATIONS) | set(UNPORTED_OPERATIONS)
    unclassified = operations - classified
    stale = classified - operations
    assert not unclassified, (
        f"New facade dispatch operation(s) not classified by Phase 6C: "
        f"{sorted(unclassified)}. Add each to SHIPPED_OPERATIONS or "
        f"UNPORTED_OPERATIONS in {Path(__file__).name}."
    )
    assert not stale, (
        f"Classified operation(s) no longer present in any facade: {sorted(stale)}. "
        f"Remove them from {Path(__file__).name} or restore the dispatch site."
    )
