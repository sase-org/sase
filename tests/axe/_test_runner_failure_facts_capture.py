"""Capture and extraction tests for runner failure facts."""

from __future__ import annotations

import ast
import sys
from pathlib import Path
from types import SimpleNamespace

from sase.axe import runner_failure_facts as facts_mod
from sase.llm_provider.types import LLMInvocationError
from sase.macro.workflow_models import WorkflowExecutionError
from tests.axe._runner_failure_facts_helpers import clean_lifecycle as clean_lifecycle


def _raise_import_error() -> ImportError:
    try:
        from os import definitely_missing_symbol_xyz  # type: ignore[attr-defined]
    except ImportError as exc:
        return exc
    raise AssertionError("expected an ImportError")


def _raise_module_not_found() -> ModuleNotFoundError:
    try:
        import definitely_missing_module_xyz  # type: ignore[import-not-found]
    except ModuleNotFoundError as exc:
        return exc
    raise AssertionError("expected a ModuleNotFoundError")


def _raise_module_attribute_error() -> AttributeError:
    import os

    try:
        os.definitely_missing_attr_xyz  # noqa: B018
    except AttributeError as exc:
        return exc
    raise AssertionError("expected an AttributeError")


# --- chain capture -----------------------------------------------------------


def test_chain_follows_cause_and_context_outermost_first() -> None:
    try:
        try:
            raise ValueError("root")
        except ValueError as root:
            raise RuntimeError("middle") from root
    except RuntimeError as middle:
        facts = facts_mod.capture_failure_facts(middle, phase="waiting")

    chain = facts["exception_chain"]
    assert [link["type"] for link in chain] == ["RuntimeError", "ValueError"]
    assert chain[0]["message"] == "middle"
    assert chain[1]["message"] == "root"
    assert facts["lifecycle_phase"] == "waiting"
    assert facts["schema_version"] == 1
    assert facts["skew_suspect"] is False


def test_frames_come_from_innermost_exception() -> None:
    def root_failure() -> None:
        raise ImportError("root failure")

    try:
        try:
            root_failure()
        except ImportError as root:
            raise RuntimeError("wrapper") from root
    except RuntimeError as exc:
        facts = facts_mod.capture_failure_facts(exc, phase="waiting")

    assert facts["frames"][-1]["function"] == "root_failure"
    assert facts["last_frame_file"] == facts["frames"][-1]["file"]


def test_chain_is_bounded_at_eight_links() -> None:
    exc: BaseException = ValueError("link-0")
    for index in range(1, 20):
        try:
            raise RuntimeError(f"link-{index}") from exc
        except RuntimeError as wrapped:
            exc = wrapped
    facts = facts_mod.capture_failure_facts(exc, phase="waiting")
    assert len(facts["exception_chain"]) == facts_mod.MAX_CHAIN_LINKS


def test_chain_survives_cycles() -> None:
    first = ValueError("first")
    second = RuntimeError("second")
    first.__cause__ = second
    second.__cause__ = first
    facts = facts_mod.capture_failure_facts(first, phase="waiting")
    assert [link["type"] for link in facts["exception_chain"]] == [
        "ValueError",
        "RuntimeError",
    ]


def test_double_wrapped_provider_import_error_stays_visible() -> None:
    """Provider turns wrap twice; the root ImportError must still show."""
    try:
        try:
            try:
                raise ImportError(
                    "cannot import name 'auto_launch_prefix' from "
                    "'sase.monitor.continuation_delivery'"
                )
            except ImportError as root:
                raise LLMInvocationError("provider turn failed") from root
        except LLMInvocationError as turn:
            raise WorkflowExecutionError("workflow step failed") from turn
    except WorkflowExecutionError as exc:
        facts = facts_mod.capture_failure_facts(exc, phase="provider_running")

    assert [link["type"] for link in facts["exception_chain"]] == [
        "WorkflowExecutionError",
        "LLMInvocationError",
        "ImportError",
    ]
    assert facts["import_error"] is not None
    assert facts["import_error"]["missing_symbol"] == "auto_launch_prefix"
    assert facts["skew_suspect"] is True


def test_long_messages_are_truncated() -> None:
    try:
        raise ValueError("x" * 5000)
    except ValueError as exc:
        facts = facts_mod.capture_failure_facts(exc, phase="preparing")
    assert len(facts["exception_chain"][0]["message"]) == facts_mod.MAX_MESSAGE_CHARS


def test_frames_are_bounded_innermost_last() -> None:
    def deep(depth: int) -> None:
        if depth <= 0:
            raise ValueError("bottom")
        deep(depth - 1)

    try:
        deep(100)
    except ValueError as exc:
        facts = facts_mod.capture_failure_facts(exc, phase="provider_running")

    frames = facts["frames"]
    assert len(frames) == facts_mod.MAX_FRAMES
    assert frames[-1]["function"] == "deep"
    assert facts["last_frame_file"] == frames[-1]["file"]


# --- extraction rules --------------------------------------------------------


def test_import_error_extraction() -> None:
    exc = _raise_import_error()
    facts = facts_mod.capture_failure_facts(exc, phase="waiting")
    assert facts["import_error"] == {
        "name": "os",
        "path": facts["import_error"]["path"],
        "missing_symbol": "definitely_missing_symbol_xyz",
    }
    assert facts["attribute_error"] is None
    assert facts["skew_suspect"] is True


def test_module_not_found_extraction() -> None:
    exc = _raise_module_not_found()
    facts = facts_mod.capture_failure_facts(exc, phase="waiting")
    assert facts["import_error"]["name"] == "definitely_missing_module_xyz"
    assert facts["import_error"]["missing_symbol"] is None
    assert facts["skew_suspect"] is True


def test_module_attribute_error_extraction() -> None:
    exc = _raise_module_attribute_error()
    facts = facts_mod.capture_failure_facts(exc, phase="waiting")
    assert facts["attribute_error"] == {
        "module": "os",
        "attribute": "definitely_missing_attr_xyz",
    }
    assert facts["skew_suspect"] is True


def test_instance_attribute_error_is_not_extracted() -> None:
    try:
        SimpleNamespace().definitely_missing_attr_xyz  # noqa: B018
    except AttributeError as exc:
        facts = facts_mod.capture_failure_facts(exc, phase="waiting")
    assert facts["attribute_error"] is None
    # AttributeError is still prefilter-positive; core scopes the origin.
    assert facts["skew_suspect"] is True
    assert facts["exception_chain"][0]["type"] == "AttributeError"


def test_plain_errors_are_not_skew_suspect() -> None:
    for error in (
        ValueError("bad value"),
        TypeError("signature mismatch"),
        RuntimeError("boom"),
        NameError("missing_name"),
    ):
        facts = facts_mod.capture_failure_facts(error, phase="preparing")
        assert facts["skew_suspect"] is False
        assert facts["import_error"] is None
        assert facts["attribute_error"] is None


def test_prefilter_covers_tier_two_and_three_text() -> None:
    tier_two = facts_mod.capture_failure_facts(
        RuntimeError("sase_core_rs is importable but does not expose binding 'X'"),
        phase="preparing",
    )
    assert tier_two["skew_suspect"] is True
    tier_three = facts_mod.capture_failure_facts(
        RuntimeError("artifact was written by a newer or unknown sase version"),
        phase="preparing",
    )
    assert tier_three["skew_suspect"] is True


def test_phase_only_facts_carry_phase_and_text_prefilter() -> None:
    facts = facts_mod.capture_failure_facts(None, phase="finalizing")
    assert facts["exception_chain"] == []
    assert facts["frames"] == []
    assert facts["lifecycle_phase"] == "finalizing"
    assert facts["skew_suspect"] is False

    skew_text = facts_mod.capture_failure_facts(
        None,
        phase="finalizing",
        error_text="ImportError: cannot import name 'x' from 'sase.y'",
    )
    assert skew_text["skew_suspect"] is True


def test_capture_never_raises() -> None:
    class BadRepr(Exception):
        def __str__(self) -> str:
            raise RuntimeError("no message for you")

    facts = facts_mod.capture_failure_facts(BadRepr(), phase="waiting")
    assert facts["exception_chain"][0]["message"] == "<unprintable>"


# --- stdlib-only firewall ----------------------------------------------------


def test_failure_facts_module_is_stdlib_only_with_no_local_imports() -> None:
    path = Path(facts_mod.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))

    class ImportVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.top_level: list[str] = []
            self.nested: list[str] = []

        def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
            self._record(node, [alias.name for alias in node.names])

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
            module = node.module or ""
            self._record(node, [module])

        def _record(self, node: ast.AST, names: list[str]) -> None:
            target = self.nested if _inside_function(node, tree) else self.top_level
            target.extend(names)

    visitor = ImportVisitor()
    visitor.visit(tree)
    assert visitor.nested == []
    allowed = set(sys.stdlib_module_names) | {"__future__"}
    for name in visitor.top_level:
        assert name.split(".")[0] in allowed, f"non-stdlib import: {name}"


def _inside_function(node: ast.AST, tree: ast.AST) -> bool:
    for parent in ast.walk(tree):
        if not isinstance(
            parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            continue
        if node in ast.walk(parent) and node is not parent:
            # Confirm the node is genuinely nested, not the def itself.
            for child in ast.walk(parent):
                if child is node:
                    return True
    return False
