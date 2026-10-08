"""Architecture and route tests for the shadow instruction boundary (E2).

The architecture test keeps ``invoke_with_instructions`` the only root
``provider.invoke`` caller. The route tests drive the boundary with a fake
provider over a tmp artifacts dir and fixture project/home roots.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
from typing import Any

import pytest

from sase.feature_flags import override_flags
from sase.llm_provider._instruction_boundary import (
    AGENT_META_KEY,
    INSTRUCTIONS_DIR_NAME,
    invoke_with_instructions,
)
from sase.llm_provider.types import InvokeResult
from tests.instructions.fixture_compiler import make_roots

ROOT = Path(__file__).parents[2]
SRC = ROOT / "src" / "sase"
BOUNDARY_REL = "src/sase/llm_provider/_instruction_boundary.py"

#: ``relpath:function`` entries allowed to call ``*.invoke`` directly, each
#: with a one-line reason.
ALLOWLIST = {
    # Adapter ``llm_invoke`` hookimpls delegate to their own ``self.invoke``;
    # they are the leaf providers, not root invocation sites.
    "src/sase/llm_provider/agy.py:llm_invoke",
    "src/sase/llm_provider/claude.py:llm_invoke",
    "src/sase/llm_provider/codex.py:llm_invoke",
    "src/sase/llm_provider/fakey.py:llm_invoke",
    "src/sase/llm_provider/grok.py:llm_invoke",
    "src/sase/llm_provider/muse_provider.py:llm_invoke",
    "src/sase/llm_provider/opencode.py:llm_invoke",
    "src/sase/llm_provider/qwen.py:llm_invoke",
}

#: Root sites that must route through the boundary, with their purpose.
BOUNDARY_CALLERS = {
    "src/sase/llm_provider/_invoke.py": "ordinary",
    "src/sase/finalizers/declaration_recovery.py": "declaration_recovery",
    "src/sase/finalizers/commit_repair_conflict.py": "conflict_repair",
}


def _enclosing_name(tree: ast.AST, lineno: int) -> str:
    """Return the innermost function name containing *lineno*."""
    best = ""
    best_depth = -1

    def visit(node: ast.AST, depth: int, trail: list[str]) -> None:
        nonlocal best, best_depth
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.lineno
            end = getattr(node, "end_lineno", None) or start
            if start <= lineno <= end and depth > best_depth:
                best = node.name
                best_depth = depth
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, depth + 1, trail)
            else:
                visit(child, depth, trail)

    visit(tree, 0, [])
    return best or "<module>"


def _invoke_calls(path: Path) -> list[tuple[str, int, ast.Call]]:
    """Return ``(function, lineno, node)`` for every ``*.invoke(...)`` call."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[str, int, ast.Call]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "invoke":
            found.append((_enclosing_name(tree, node.lineno), node.lineno, node))
    return found


def test_only_boundary_calls_provider_invoke() -> None:
    """No root ``*.invoke`` call lives outside the boundary or allowlist."""
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        rel = str(path.relative_to(ROOT))
        for function, lineno, _node in _invoke_calls(path):
            if rel == BOUNDARY_REL:
                continue
            if f"{rel}:{function}" in ALLOWLIST:
                continue
            offenders.append(f"{rel}:{function}:{lineno}")
    assert offenders == []


def test_allowlist_entries_still_exist() -> None:
    """Every allowlist entry still names a real ``*.invoke`` call site."""
    seen: set[str] = set()
    for path in sorted(SRC.rglob("*.py")):
        rel = str(path.relative_to(ROOT))
        for function, _lineno, _node in _invoke_calls(path):
            if rel != BOUNDARY_REL:
                seen.add(f"{rel}:{function}")
    missing = sorted(entry for entry in ALLOWLIST if entry not in seen)
    assert missing == []


@pytest.mark.parametrize(("relpath", "purpose"), sorted(BOUNDARY_CALLERS.items()))
def test_root_sites_route_through_boundary(relpath: str, purpose: str) -> None:
    """Each root site calls ``invoke_with_instructions`` with its purpose."""
    path = ROOT / relpath
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "invoke_with_instructions"
        and any(
            keyword.arg == "purpose"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value == purpose
            for keyword in node.keywords
        )
    ]
    assert matches, f"{relpath} must call invoke_with_instructions({purpose!r})"


class _FakeProvider:
    """Minimal execution provider double that records invocations."""

    def __init__(self, name: str = "fakey") -> None:
        self._name = name
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.seen_env: list[str | None] = []

    def provider_name(self) -> str:
        return self._name

    def resolve_model_name(self, model_tier: str = "large") -> str:
        return f"{self._name}-{model_tier}"

    def invoke(self, prompt: str, **kwargs: Any) -> InvokeResult:
        self.calls.append((prompt, kwargs))
        self.seen_env.append(os.environ.get("SASE_INSTRUCTIONS_FILE"))
        return InvokeResult(content="fake-reply", usage=None)


@pytest.fixture()
def shadow_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Isolate instructions home/store, project root, and agent identity."""
    project_root, _home_root = make_roots(tmp_path)
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"exec_llm_provider": "fakey"}), encoding="utf-8"
    )
    monkeypatch.setenv("SASE_INSTRUCTIONS_HOME", str(tmp_path / "ihome"))
    monkeypatch.setenv("SASE_ACTIVE_PROJECT_DIR", str(project_root))
    monkeypatch.setenv("SASE_AGENT_NAME", "boundary-test-agent")
    monkeypatch.delenv("SASE_INSTRUCTIONS_FILE", raising=False)
    return {"artifacts_dir": str(artifacts_dir), "project_root": project_root}


def _manifest(artifacts_dir: str, name: str) -> dict[str, Any]:
    with open(
        Path(artifacts_dir) / INSTRUCTIONS_DIR_NAME / name, encoding="utf-8"
    ) as handle:
        return json.load(handle)


def _meta(artifacts_dir: str) -> dict[str, Any]:
    with open(Path(artifacts_dir) / "agent_meta.json", encoding="utf-8") as handle:
        return json.load(handle)


def _invoke_kwargs(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model_tier": "large",
        "suppress_output": True,
        "model_override": None,
        "options": None,
    }
    kwargs.update(overrides)
    return kwargs


def test_ordinary_route_writes_bundle_manifest_meta_and_env(
    shadow_env: dict[str, Any],
) -> None:
    """The ordinary route records a shadow manifest and restores the env."""
    provider = _FakeProvider()
    with override_flags(instruction_shadow_render=True):
        result = invoke_with_instructions(
            provider,
            "hello",
            purpose="ordinary",
            artifacts_dir=shadow_env["artifacts_dir"],
            provider_name="fakey",
            agent_type="editor",
            **_invoke_kwargs(),
        )
    assert result.content == "fake-reply"
    assert len(provider.calls) == 1
    instructions = Path(shadow_env["artifacts_dir"]) / INSTRUCTIONS_DIR_NAME
    assert (instructions / "00-fakey.md").is_file()
    manifest = _manifest(shadow_env["artifacts_dir"], "00-fakey.json")
    assert manifest["delivery"]["status"] == "shadow"
    assert manifest["facts"]["purpose"] == "ordinary"
    assert manifest["facts"]["provider"] == "fakey"
    assert manifest["facts"]["actor"] == "sase_root"
    assert manifest["delivery"]["agent_type"] == "editor"
    assert manifest["delivery"]["agent_name"] == "boundary-test-agent"
    assert manifest["delivery"]["invocation_seq"] == 0
    assert manifest["delivery"]["attempt"] == 1
    assert manifest["delivery"]["render_ms"] >= 0
    assert manifest["delivery"]["cache"] in ("hit", "miss", "bypass")
    assert manifest["bundle"]["common_digest"]
    # The env var held the bundle path during the call, then was restored.
    assert provider.seen_env == [str(instructions / "00-fakey.md")]
    assert "SASE_INSTRUCTIONS_FILE" not in os.environ
    summary = _meta(shadow_env["artifacts_dir"])[AGENT_META_KEY]
    assert summary["schema_version"] == 1
    assert summary["count"] == 1
    assert summary["latest"]["seq"] == 0
    assert summary["latest"]["provider"] == "fakey"
    assert summary["latest"]["purpose"] == "ordinary"
    assert summary["latest"]["sha256"] == manifest["bundle"]["sha256"]
    assert summary["latest"]["common_digest"] == manifest["bundle"]["common_digest"]
    assert summary["latest"]["manifest"] == "instructions/00-fakey.json"
    # Legacy launch evidence is untouched by the boundary.
    assert "instruction_snapshot" not in _meta(shadow_env["artifacts_dir"])


@pytest.mark.parametrize(
    ("purpose", "expected_seq"),
    [("declaration_recovery", 0), ("conflict_repair", 1)],
)
def test_finalizer_purposes_sequence(
    shadow_env: dict[str, Any], purpose: str, expected_seq: int
) -> None:
    """Recovery and repair renders record their purpose and sequence."""
    provider = _FakeProvider()
    with override_flags(instruction_shadow_render=True):
        if expected_seq == 1:
            invoke_with_instructions(
                provider,
                "first",
                purpose="declaration_recovery",
                artifacts_dir=shadow_env["artifacts_dir"],
                provider_name="fakey",
                **_invoke_kwargs(),
            )
        invoke_with_instructions(
            provider,
            "second",
            purpose=purpose,
            artifacts_dir=shadow_env["artifacts_dir"],
            provider_name="fakey",
            **_invoke_kwargs(),
        )
    name = f"{expected_seq:02d}-fakey.json"
    manifest = _manifest(shadow_env["artifacts_dir"], name)
    assert manifest["facts"]["purpose"] == purpose
    assert manifest["delivery"]["invocation_seq"] == expected_seq
    summary = _meta(shadow_env["artifacts_dir"])[AGENT_META_KEY]
    assert summary["count"] == expected_seq + 1
    assert summary["latest"]["manifest"] == f"instructions/{name}"


def test_fallback_provider_second_manifest_increments_attempt(
    shadow_env: dict[str, Any],
) -> None:
    """A retry under another provider records that provider with attempt 2."""
    artifacts = shadow_env["artifacts_dir"]
    first = _FakeProvider("fakey")
    with override_flags(instruction_shadow_render=True):
        invoke_with_instructions(
            first,
            "hello",
            purpose="ordinary",
            artifacts_dir=artifacts,
            provider_name="fakey",
            **_invoke_kwargs(),
        )
    (Path(artifacts) / "attempts" / "0").mkdir(parents=True)
    second = _FakeProvider("codex")
    with override_flags(instruction_shadow_render=True):
        invoke_with_instructions(
            second,
            "hello",
            purpose="ordinary",
            artifacts_dir=artifacts,
            provider_name="codex",
            **_invoke_kwargs(model_override="codex-model"),
        )
    manifest = _manifest(artifacts, "01-codex.json")
    assert manifest["facts"]["provider"] == "codex"
    assert manifest["delivery"]["attempt"] == 2
    assert manifest["delivery"]["model"] == "codex-model"


def test_no_artifacts_dir_invokes_directly(shadow_env: dict[str, Any]) -> None:
    """Without an artifacts dir the provider runs with no files and no env."""
    provider = _FakeProvider()
    with override_flags(instruction_shadow_render=True):
        invoke_with_instructions(
            provider,
            "hello",
            purpose="ordinary",
            artifacts_dir=None,
            provider_name="fakey",
            **_invoke_kwargs(),
        )
    assert len(provider.calls) == 1
    assert provider.seen_env == [None]
    assert "SASE_INSTRUCTIONS_FILE" not in os.environ


def test_flag_off_matches_today_behavior(shadow_env: dict[str, Any]) -> None:
    """With the flag off there are no files, no meta key, and no env var."""
    provider = _FakeProvider()
    with override_flags(instruction_shadow_render=False):
        invoke_with_instructions(
            provider,
            "hello",
            purpose="ordinary",
            artifacts_dir=shadow_env["artifacts_dir"],
            provider_name="fakey",
            agent_type="editor",
            **_invoke_kwargs(),
        )
    assert len(provider.calls) == 1
    assert not (Path(shadow_env["artifacts_dir"]) / INSTRUCTIONS_DIR_NAME).exists()
    assert AGENT_META_KEY not in _meta(shadow_env["artifacts_dir"])
    assert provider.seen_env == [None]
    assert "SASE_INSTRUCTIONS_FILE" not in os.environ


@pytest.mark.parametrize("flag_value", [True, False])
def test_flag_both_states_read(shadow_env: dict[str, Any], flag_value: bool) -> None:
    """The boundary enablement follows the flag in both states."""
    from sase.llm_provider._instruction_boundary import (
        _instruction_shadow_render_enabled,
    )

    with override_flags(instruction_shadow_render=flag_value):
        assert _instruction_shadow_render_enabled() is flag_value


def test_compiler_failure_still_invokes_and_writes_error(
    shadow_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A shadow failure writes ``.error.json`` and never blocks the call."""

    def _boom(*args: Any, **kwargs: Any) -> object:
        raise RuntimeError("compile exploded")

    monkeypatch.setattr("sase.instructions.compile.compile_bundle", _boom)
    provider = _FakeProvider()
    with override_flags(instruction_shadow_render=True):
        result = invoke_with_instructions(
            provider,
            "hello",
            purpose="ordinary",
            artifacts_dir=shadow_env["artifacts_dir"],
            provider_name="fakey",
            **_invoke_kwargs(),
        )
    assert result.content == "fake-reply"
    instructions = Path(shadow_env["artifacts_dir"]) / INSTRUCTIONS_DIR_NAME
    error = _manifest(shadow_env["artifacts_dir"], "00-fakey.error.json")
    assert error["error"]["type"] == "RuntimeError"
    assert "compile exploded" in error["error"]["message"]
    assert error["purpose"] == "ordinary"
    assert not (instructions / "00-fakey.json").exists()
    assert list(instructions.glob("*.md")) == []


def test_invoke_error_restores_env_and_propagates(
    shadow_env: dict[str, Any],
) -> None:
    """A provider failure still restores ``SASE_INSTRUCTIONS_FILE``."""

    class _Failing(_FakeProvider):
        def invoke(self, prompt: str, **kwargs: Any) -> InvokeResult:
            self.calls.append((prompt, kwargs))
            self.seen_env.append(os.environ.get("SASE_INSTRUCTIONS_FILE"))
            raise RuntimeError("provider down")

    provider = _Failing()
    with (
        override_flags(instruction_shadow_render=True),
        pytest.raises(RuntimeError, match="provider down"),
    ):
        invoke_with_instructions(
            provider,
            "hello",
            purpose="ordinary",
            artifacts_dir=shadow_env["artifacts_dir"],
            provider_name="fakey",
            **_invoke_kwargs(),
        )
    assert provider.seen_env[0] is not None
    assert "SASE_INSTRUCTIONS_FILE" not in os.environ
    assert (_manifest(shadow_env["artifacts_dir"], "00-fakey.json"))["facts"][
        "purpose"
    ] == "ordinary"


def test_provider_name_falls_back_to_agent_meta(
    shadow_env: dict[str, Any],
) -> None:
    """Finalizer sites derive the provider label without passing it."""

    class _Nameless(_FakeProvider):
        def provider_name(self) -> str:
            raise NotImplementedError("no name hook")

    provider = _Nameless()
    with override_flags(instruction_shadow_render=True):
        invoke_with_instructions(
            provider,
            "hello",
            purpose="declaration_recovery",
            artifacts_dir=shadow_env["artifacts_dir"],
            **_invoke_kwargs(),
        )
    manifest = _manifest(shadow_env["artifacts_dir"], "00-fakey.json")
    assert manifest["facts"]["provider"] == "fakey"


def test_invalid_purpose_rejected(shadow_env: dict[str, Any]) -> None:
    """An unknown purpose is a programming error, raised before invoke."""
    provider = _FakeProvider()
    with (
        override_flags(instruction_shadow_render=True),
        pytest.raises(ValueError, match="invalid shadow purpose"),
    ):
        invoke_with_instructions(
            provider,
            "hello",
            purpose="soak",
            artifacts_dir=shadow_env["artifacts_dir"],
            **_invoke_kwargs(),
        )
    assert provider.calls == []


def test_read_run_manifests_round_trip(shadow_env: dict[str, Any]) -> None:
    """The reader validates writer output and flags missing/corrupt files."""
    from sase.instructions.manifests import read_run_manifests

    provider = _FakeProvider()
    with override_flags(instruction_shadow_render=True):
        invoke_with_instructions(
            provider,
            "hello",
            purpose="ordinary",
            artifacts_dir=shadow_env["artifacts_dir"],
            provider_name="fakey",
            **_invoke_kwargs(),
        )
    records = read_run_manifests(shadow_env["artifacts_dir"])
    assert [(record.seq, record.provider) for record in records] == [(0, "fakey")]
    assert records[0].manifest is not None
    assert records[0].manifest["delivery"]["status"] == "shadow"
    assert records[0].error is None
    assert records[0].problems == ()
    assert records[0].bundle_path is not None and records[0].bundle_path.is_file()

    instructions = Path(shadow_env["artifacts_dir"]) / INSTRUCTIONS_DIR_NAME
    (instructions / "00-fakey.json").write_text("{not json", encoding="utf-8")
    (instructions / "01-fakey.error.json").write_text(
        json.dumps({"provider": "fakey"}), encoding="utf-8"
    )
    records = read_run_manifests(shadow_env["artifacts_dir"])
    assert [record.seq for record in records] == [0, 1]
    assert records[0].manifest is None
    assert any("corrupt" in problem for problem in records[0].problems)
    assert records[1].manifest is None
    assert records[1].error == {"provider": "fakey"}
    assert read_run_manifests(shadow_env["artifacts_dir"] + "-missing") == []
