"""Tests for runner failure facts, the skew prefilter, and lifecycle crumbs."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from sase.axe import runner_failure_facts as facts_mod
from sase.axe import runner_lifecycle_phase as lifecycle_mod
from sase.axe.run_agent_directive_metadata import preserved_agent_metadata
from sase.axe.run_agent_markers import build_done_marker
from sase.axe.run_agent_runner_errors import RunnerErrorContext, record_runner_error
from sase.axe.run_agent_runner_finalize import write_error_done_marker
from sase.axe.run_agent_runner_lifecycle import _ensure_failed_done_marker
from sase.axe.run_agent_exec import LoopState, _finalize_loop
from sase.axe.run_agent_exec_retry import RetryTracker
from sase.llm_provider.types import LLMInvocationError
from sase.macro.workflow_models import WorkflowExecutionError
from tests._axe_run_agent_exec_helpers import make_exec_ctx
from tests._run_agent_runner_lifecycle_helpers import make_context, make_state


@pytest.fixture(autouse=True)
def _clean_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lifecycle_mod, "_current_phase", None)
    # Lifecycle breadcrumb writes resolve the index updater lazily, so this
    # keeps breadcrumb tests off the real artifact index.
    patcher = patch(
        "sase.core.agent_artifact_index_lifecycle."
        "update_agent_artifact_index_for_marker_mutation",
        MagicMock(),
    )
    patcher.start()
    try:
        yield
    finally:
        patcher.stop()
        monkeypatch.setattr(lifecycle_mod, "_current_phase", None)


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


# --- lifecycle breadcrumbs ---------------------------------------------------


def test_breadcrumbs_are_written_in_order_and_bounded(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text("{}", encoding="utf-8")

    lifecycle_mod.mark_lifecycle_phase(str(artifacts), "booting")
    lifecycle_mod.mark_lifecycle_phase(str(artifacts), "waiting")
    assert lifecycle_mod.current_lifecycle_phase() == "waiting"
    meta = json.loads((artifacts / "agent_meta.json").read_text(encoding="utf-8"))
    assert [entry["phase"] for entry in meta["lifecycle_phases"]] == [
        "booting",
        "waiting",
    ]

    for _ in range(20):
        lifecycle_mod.mark_lifecycle_phase(str(artifacts), "preparing")
    meta = json.loads((artifacts / "agent_meta.json").read_text(encoding="utf-8"))
    assert meta["lifecycle_phase"] == "preparing"
    assert meta["lifecycle_phase_at"]
    assert len(meta["lifecycle_phases"]) == lifecycle_mod.MAX_HISTORY_ENTRIES
    assert {entry["phase"] for entry in meta["lifecycle_phases"]} == {"preparing"}


def test_mark_with_missing_meta_updates_memory_only(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    assert lifecycle_mod.mark_lifecycle_phase(str(missing), "booting") == "booting"
    assert lifecycle_mod.current_lifecycle_phase() == "booting"
    assert not (missing / "agent_meta.json").exists()


def test_mark_rejects_unknown_phases() -> None:
    lifecycle_mod.mark_lifecycle_phase(None, "booting")
    assert lifecycle_mod.mark_lifecycle_phase(None, "nope") == "booting"
    assert lifecycle_mod.current_lifecycle_phase() == "booting"


def test_mark_never_raises_on_unwritable_dir(tmp_path: Path) -> None:
    block = tmp_path / "block"
    block.write_text("not a dir", encoding="utf-8")
    assert lifecycle_mod.mark_lifecycle_phase(str(block), "waiting") == "waiting"


# --- boot identity -----------------------------------------------------------


def test_boot_code_identity_covers_host_core_and_plugins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lifecycle_mod, "_boot_cache", None)
    try:
        identity, booted_at, elapsed_ms = lifecycle_mod.boot_code_identity()
    finally:
        monkeypatch.setattr(lifecycle_mod, "_boot_cache", None)
    assert identity["schema_version"] == 1
    assert identity["captured_at"]
    assert booted_at
    assert elapsed_ms >= 0
    by_role = {root["role"] for root in identity["roots"]}
    assert {"host", "core"} <= by_role
    host = next(root for root in identity["roots"] if root["role"] == "host")
    assert host["name"] == "sase"
    assert host["version"]
    assert host["install_type"] in {"editable", "wheel", "unknown"}
    for root in identity["roots"]:
        assert set(root) == {
            "name",
            "role",
            "version",
            "commit",
            "source_root",
            "install_type",
        }


def test_boot_code_identity_is_memoized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(lifecycle_mod, "_boot_cache", None)
    try:
        first = lifecycle_mod.boot_code_identity(startup_commit="abc")
        second = lifecycle_mod.boot_code_identity()
    finally:
        monkeypatch.setattr(lifecycle_mod, "_boot_cache", None)
    assert first[0] is second[0]


def test_boot_code_identity_uses_first_distribution_record_on_sys_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib.metadata

    class _Distribution:
        def __init__(self, name: str, version: str) -> None:
            self.metadata = {"Name": name, "Version": version}

    first_host = _Distribution("sase", "first-host")
    first_core = _Distribution("sase-core-rs", "first-core")
    first_plugin = _Distribution("sase-plugin-example", "first-plugin")
    records = [
        first_host,
        _Distribution("sase", "later-host"),
        first_core,
        _Distribution("sase-core-rs", "later-core"),
        first_plugin,
        _Distribution("sase-plugin-example", "later-plugin"),
    ]
    selected: list[tuple[str, str]] = []

    def package_record(
        dist: _Distribution,
        distribution_name: str,
        *,
        role: str,
        **_kwargs: object,
    ) -> dict[str, str]:
        selected.append((role, dist.metadata["Version"]))
        return {
            "name": distribution_name,
            "role": role,
            "version": dist.metadata["Version"],
        }

    monkeypatch.setattr(importlib.metadata, "distributions", lambda: records)
    monkeypatch.setattr(lifecycle_mod, "_package_root_from_dist", package_record)
    monkeypatch.setattr(lifecycle_mod, "_boot_cache", None)
    try:
        identity = lifecycle_mod._capture_boot_code_identity(startup_commit=None)
    finally:
        monkeypatch.setattr(lifecycle_mod, "_boot_cache", None)

    assert selected == [
        ("host", "first-host"),
        ("core", "first-core"),
        ("plugin", "first-plugin"),
    ]
    assert len(identity["roots"]) == 3


def test_preserved_metadata_keeps_identity_and_breadcrumbs(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "code_identity": {"schema_version": 1, "roots": []},
                "booted_at": "2026-10-09T00:00:00+00:00",
                "lifecycle_phase": "waiting",
                "lifecycle_phase_at": "2026-10-09T00:01:00+00:00",
                "lifecycle_phases": [{"phase": "waiting", "at": "x"}],
            }
        ),
        encoding="utf-8",
    )
    preserved = preserved_agent_metadata(str(artifacts))
    assert preserved["code_identity"] == {"schema_version": 1, "roots": []}
    assert preserved["booted_at"] == "2026-10-09T00:00:00+00:00"
    assert preserved["lifecycle_phase"] == "waiting"
    assert preserved["lifecycle_phase_at"] == "2026-10-09T00:01:00+00:00"
    assert preserved["lifecycle_phases"] == [{"phase": "waiting", "at": "x"}]


# --- done.json facts ---------------------------------------------------------


def _error_context(tmp_path: Path) -> RunnerErrorContext:
    return RunnerErrorContext(
        current_artifacts_dir=str(tmp_path),
        cl_name="cl",
        project_file="/tmp/project.sase",
        timestamp="20261009_120000",
        artifacts_timestamp="20261009120000",
        workspace_num=1,
        workspace_dir=str(tmp_path / "workspace"),
        output_path=str(tmp_path / "output.log"),
        agent_name="worker",
        agent_model="model",
        agent_llm_provider="provider",
        agent_vcs_provider=None,
        agent_hidden=False,
    )


def test_raised_failure_writes_facts_to_done_json(tmp_path: Path) -> None:
    lifecycle_mod.mark_lifecycle_phase(None, "waiting")
    kills = SimpleNamespace(labels=MagicMock(return_value=MagicMock()))
    try:
        raise ImportError("cannot import name 'gone' from 'sase.somewhere'")
    except ImportError as exc:
        record_runner_error(
            exc,
            context=_error_context(tmp_path),
            write_error_done_marker=write_error_done_marker,
            agent_kills=kills,
            message_prefix="Error running agent",
        )
    done = json.loads((tmp_path / "done.json").read_text(encoding="utf-8"))
    facts = done["failure_facts"]
    assert facts["lifecycle_phase"] == "waiting"
    assert facts["skew_suspect"] is True
    assert facts["import_error"]["missing_symbol"] == "gone"
    assert facts["exception_chain"][0]["type"] == "ImportError"


def test_shutdown_path_writes_phase_only_facts(tmp_path: Path) -> None:
    lifecycle_mod.mark_lifecycle_phase(None, "finalizing")
    context = make_context(tmp_path)
    state = make_state(
        current_artifacts_dir=str(tmp_path),
        error_summary="RuntimeError: boom",
        error_traceback_str="",
    )
    _ensure_failed_done_marker(
        context=context,
        state=state,
        write_error_done_marker=write_error_done_marker,
    )
    done = json.loads((tmp_path / "done.json").read_text(encoding="utf-8"))
    assert done["failure_facts"]["lifecycle_phase"] == "finalizing"
    assert done["failure_facts"]["exception_chain"] == []
    assert done["failure_facts"]["skew_suspect"] is False


def test_finalize_loop_failed_outcome_writes_phase_facts(
    tmp_path: Path,
) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    state = LoopState(
        current_prompt="prompt",
        current_role_suffix="",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="failed",
        sdd_spec_path=None,
        original_prompt="prompt",
    )
    lifecycle_mod.mark_lifecycle_phase(None, "provider_done")
    with (
        patch(
            "sase.axe.run_agent_exec_finalize.save_chat_history",
            return_value=str(tmp_path / "chat.md"),
        ),
        patch(
            "sase.axe.image_attachments.collect_agent_markdown_paths",
            return_value=[],
        ),
        patch(
            "sase.axe.image_attachments.collect_agent_image_paths",
            return_value=[],
        ),
    ):
        _finalize_loop(ctx, state, RetryTracker(retry_cfg=None), None)

    done = json.loads(
        (Path(ctx.artifacts_dir) / "done.json").read_text(encoding="utf-8")
    )
    assert done["outcome"] == "failed"
    assert done["failure_facts"]["lifecycle_phase"] == "finalizing"
    assert done["failure_facts"]["skew_suspect"] is False


def test_finalize_loop_handoff_finalizer_failure_keeps_handoff_facts(
    tmp_path: Path,
) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    Path(ctx.artifacts_dir, "finalizer_result.json").write_text(
        json.dumps({"status": "failed"}), encoding="utf-8"
    )
    state = LoopState(
        current_prompt="prompt",
        current_role_suffix="",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="monitored",
        sdd_spec_path=None,
        original_prompt="prompt",
    )
    lifecycle_mod.mark_lifecycle_phase(None, "handoff")
    with (
        patch(
            "sase.axe.run_agent_exec_finalize.save_chat_history",
            return_value=str(tmp_path / "chat.md"),
        ),
        patch(
            "sase.axe.image_attachments.collect_agent_markdown_paths",
            return_value=[],
        ),
        patch(
            "sase.axe.image_attachments.collect_agent_image_paths",
            return_value=[],
        ),
    ):
        _finalize_loop(ctx, state, RetryTracker(retry_cfg=None), None)

    done = json.loads(
        (Path(ctx.artifacts_dir) / "done.json").read_text(encoding="utf-8")
    )
    assert done["outcome"] == "failed"
    assert done["failure_facts"]["lifecycle_phase"] == "handoff"


def test_nonfailure_finalize_outcome_omits_failure_facts(tmp_path: Path) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    state = LoopState(
        current_prompt="prompt",
        current_role_suffix="",
        current_artifacts_dir=ctx.artifacts_dir,
        loop_outcome="stopped",
        sdd_spec_path=None,
        original_prompt="prompt",
    )
    with (
        patch(
            "sase.axe.run_agent_exec_finalize.save_chat_history",
            return_value=str(tmp_path / "chat.md"),
        ),
        patch(
            "sase.axe.image_attachments.collect_agent_markdown_paths",
            return_value=[],
        ),
        patch(
            "sase.axe.image_attachments.collect_agent_image_paths",
            return_value=[],
        ),
    ):
        _finalize_loop(ctx, state, RetryTracker(retry_cfg=None), None)

    done = json.loads(
        (Path(ctx.artifacts_dir) / "done.json").read_text(encoding="utf-8")
    )
    assert done["outcome"] == "stopped"
    assert "failure_facts" not in done


def test_build_done_marker_omits_facts_by_default() -> None:
    marker = build_done_marker(
        "cl",
        "/tmp/project.sase",
        "20261009_120000",
        "20261009120000",
        1,
        "/tmp/workspace",
        "/tmp/output.log",
        "failed",
        error="RuntimeError: boom",
        traceback_str="trace",
    )
    assert "failure_facts" not in marker
