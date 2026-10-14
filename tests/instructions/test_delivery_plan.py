"""Route tests for the E3 delivery-plan boundary and hook."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from sase.llm_provider._instruction_boundary import (
    AGENT_META_KEY,
    INSTRUCTIONS_DIR_NAME,
    invoke_with_instructions,
)
from sase.feature_flags import override_flags
from sase.llm_provider.instruction_delivery import (
    CHANNEL_CLAUDE_ROOT,
    CHANNEL_CLAUDE_SUBAGENT,
    MARKER_RE,
    current_instruction_delivery,
    delivered_text,
    legacy_instruction_delivery,
    resolve_delivery_plan,
    sase_owned_instruction_paths,
)
from sase.llm_provider.registry import create_provider
from sase.llm_provider.types import InvokeResult
from tests.instructions.fixture_compiler import make_roots


class _FakeProvider:
    """Minimal execution provider double that records invocations."""

    def __init__(self, name: str = "fakey") -> None:
        self._name = name
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.seen_env: list[str | None] = []
        self.seen_delivery: list[Any] = []

    def provider_name(self) -> str:
        return self._name

    def resolve_model_name(self, model_tier: str = "large") -> str:
        return f"{self._name}-{model_tier}"

    def invoke(self, prompt: str, **kwargs: Any) -> InvokeResult:
        self.calls.append((prompt, kwargs))
        self.seen_env.append(os.environ.get("SASE_INSTRUCTIONS_FILE"))
        delivery = current_instruction_delivery()
        self.seen_delivery.append(delivery)
        if delivery is not None:
            delivery.record_session("sess-1")
        return InvokeResult(content="fake-reply", usage=None)


class _ExplicitProvider(_FakeProvider):
    """Fake whose plan is explicit root and helper."""

    def instruction_delivery(self) -> dict[str, Any]:
        return {
            "root": {"status": "explicit", "channel": CHANNEL_CLAUDE_ROOT},
            "subagent": {
                "status": "explicit",
                "channel": CHANNEL_CLAUDE_SUBAGENT,
            },
        }


class _OversizeProvider(_ExplicitProvider):
    def instruction_delivery(self) -> dict[str, Any]:
        return {
            "root": {
                "status": "explicit",
                "channel": CHANNEL_CLAUDE_ROOT,
                "max_bytes": 10,
            },
            "subagent": {"status": "inherits_native", "reason": "provider_legacy"},
        }


class _RaisingHookProvider(_FakeProvider):
    def instruction_delivery(self) -> dict[str, Any]:
        raise RuntimeError("hook exploded")


class _AdapterFallbackProvider(_ExplicitProvider):
    def invoke(self, prompt: str, **kwargs: Any) -> InvokeResult:
        self.calls.append((prompt, kwargs))
        self.seen_env.append(os.environ.get("SASE_INSTRUCTIONS_FILE"))
        delivery = current_instruction_delivery()
        self.seen_delivery.append(delivery)
        if delivery is not None:
            delivery.record_session("sess-fail")
            delivery.report_fallback("root", "delivery_failed", "adapter boom")
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
    monkeypatch.setenv("SASE_AGENT_NAME", "delivery-test-agent")
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


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_declared_legacy_hookimpls_resolve_to_provider_legacy() -> None:
    """Providers without an explicit phase still declare legacy native discovery."""
    for name in ("agy", "qwen", "opencode", "fakey"):
        plan = resolve_delivery_plan(create_provider(name))
        assert plan.root.status == "inherits_native"
        assert plan.root.reason == "provider_legacy"
        assert plan.subagent.status == "inherits_native"
        assert plan.subagent.reason == "provider_legacy"
        assert create_provider(name).instruction_delivery() == (
            legacy_instruction_delivery()
        )


def test_grok_and_muse_delivery_flags_select_explicit_slots() -> None:
    with override_flags(grok_explicit_instructions=True):
        grok = resolve_delivery_plan(create_provider("grok"))
    assert grok.root.status == "explicit"
    assert grok.root.channel == "grok.rules"
    assert grok.root.max_bytes == 120 * 1024
    assert grok.subagent.status == "none"

    with override_flags(grok_explicit_instructions=False):
        grok = resolve_delivery_plan(create_provider("grok"))
    assert grok.root.status == "inherits_native"
    assert grok.root.reason == "flag_disabled"
    assert grok.subagent.status == "inherits_native"
    assert grok.subagent.reason == "flag_disabled"

    with override_flags(muse_explicit_instructions=True):
        muse = resolve_delivery_plan(create_provider("muse"))
    assert muse.root.status == "explicit"
    assert muse.root.channel == "muse.prompt_prefix"
    assert muse.subagent.status == "none"

    with override_flags(muse_explicit_instructions=False):
        muse = resolve_delivery_plan(create_provider("muse"))
    assert muse.root.status == "inherits_native"
    assert muse.root.reason == "flag_disabled"
    assert muse.subagent.status == "inherits_native"
    assert muse.subagent.reason == "flag_disabled"


def test_missing_and_raising_hooks_resolve_to_legacy() -> None:
    """No method, a raising method, and an invalid payload all become legacy."""
    assert resolve_delivery_plan(_FakeProvider()).root.reason == "provider_legacy"
    assert resolve_delivery_plan(_RaisingHookProvider()).root.reason == (
        "provider_legacy"
    )
    assert resolve_delivery_plan(object()).root.reason == "provider_legacy"

    class _Invalid:
        def instruction_delivery(self) -> dict[str, Any]:
            return {"root": {"status": "none"}}

    assert resolve_delivery_plan(_Invalid()).root.status == "inherits_native"


def test_explicit_root_and_helper_writes_v2_manifest_and_session_id(
    shadow_env: dict[str, Any],
) -> None:
    """Explicit slots write root and helper files, a marker, and session ids."""
    provider = _ExplicitProvider("claude")
    invoke_with_instructions(
        provider,
        "hello",
        purpose="ordinary",
        artifacts_dir=shadow_env["artifacts_dir"],
        provider_name="claude",
        agent_type="editor",
        **_invoke_kwargs(),
    )
    artifacts = Path(shadow_env["artifacts_dir"])
    instructions = artifacts / INSTRUCTIONS_DIR_NAME
    root_md = instructions / "00-claude.md"
    helper_md = instructions / "00-claude.helper.md"
    assert root_md.is_file()
    assert helper_md.is_file()
    assert _mode(root_md) == 0o644
    assert _mode(helper_md) == 0o644
    assert _mode(instructions / "00-claude.json") == 0o644
    manifest = _manifest(shadow_env["artifacts_dir"], "00-claude.json")
    assert manifest["schema_version"] == 2
    assert manifest["delivery"]["status"] == "explicit"
    assert manifest["delivery"]["channel"] == CHANNEL_CLAUDE_ROOT
    assert manifest["delivery"]["session_ids"] == ["sess-1"]
    assert "fallback" not in manifest["delivery"]
    subagent = manifest["delivery"]["subagent"]
    assert subagent["status"] == "explicit"
    assert subagent["channel"] == CHANNEL_CLAUDE_SUBAGENT
    assert len(subagent["bundle_sha256"]) == 64
    helper = _manifest(shadow_env["artifacts_dir"], "00-claude.helper.json")
    assert helper["facts"]["actor"] == "native_helper"
    assert helper["delivery"]["status"] == "explicit"
    assert (
        helper["delivery"]["parent_invocation_id"]
        == (manifest["delivery"]["invocation_id"])
    )
    seen = provider.seen_delivery[0]
    assert seen is not None
    assert seen.root.plan.status == "explicit"
    assert seen.root.text is not None
    assert MARKER_RE.search(seen.root.text)
    assert seen.invocation_id == manifest["delivery"]["invocation_id"]
    assert (
        delivered_text(
            root_md.read_text(encoding="utf-8"),
            manifest["bundle"]["sha256"],
            manifest["delivery"]["invocation_id"],
        )
        == seen.root.text
    )
    summary = _meta(shadow_env["artifacts_dir"])[AGENT_META_KEY]
    assert summary["latest"]["delivery_status"] == "explicit"
    assert summary["latest"]["helper_manifest"] == (
        "instructions/00-claude.helper.json"
    )
    assert current_instruction_delivery() is None


def test_legacy_hookimpl_writes_fallback(
    shadow_env: dict[str, Any],
) -> None:
    """A declared-legacy hook records inherits_native plus provider_legacy."""
    provider = _FakeProvider()
    invoke_with_instructions(
        provider,
        "hello",
        purpose="ordinary",
        artifacts_dir=shadow_env["artifacts_dir"],
        provider_name="fakey",
        **_invoke_kwargs(),
    )
    manifest = _manifest(shadow_env["artifacts_dir"], "00-fakey.json")
    assert manifest["delivery"]["status"] == "inherits_native"
    assert manifest["delivery"]["fallback"]["reason"] == "provider_legacy"
    assert provider.seen_delivery[0] is not None
    assert provider.seen_delivery[0].root.plan.status == "inherits_native"


def test_raising_hook_is_legacy_with_active_delivery(
    shadow_env: dict[str, Any],
) -> None:
    """A raising hook still records a legacy plan and invokes."""
    provider = _RaisingHookProvider()
    invoke_with_instructions(
        provider,
        "hello",
        purpose="ordinary",
        artifacts_dir=shadow_env["artifacts_dir"],
        provider_name="fakey",
        **_invoke_kwargs(),
    )
    manifest = _manifest(shadow_env["artifacts_dir"], "00-fakey.json")
    assert manifest["delivery"]["fallback"]["reason"] == "provider_legacy"


def test_render_failure_notifies_once(
    shadow_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Render failure writes error.json, skips active delivery, and dedupes."""
    calls: list[tuple[str, str]] = []

    def _boom(*args: Any, **kwargs: Any) -> object:
        raise RuntimeError("compile exploded")

    def _notify(provider: str, reason: str, *, detail: str | None = None) -> None:
        calls.append((provider, reason))

    monkeypatch.setattr("sase.instructions.compile.compile_bundle", _boom)
    monkeypatch.setattr(
        "sase.llm_provider.instruction_delivery.notify_instruction_fallback",
        _notify,
    )
    provider = _FakeProvider()
    for _ in range(2):
        invoke_with_instructions(
            provider,
            "hello",
            purpose="ordinary",
            artifacts_dir=shadow_env["artifacts_dir"],
            provider_name="fakey",
            **_invoke_kwargs(),
        )
    assert [delivery is None for delivery in provider.seen_delivery] == [True, True]
    assert calls == [("fakey", "render_failed"), ("fakey", "render_failed")]
    error = _manifest(shadow_env["artifacts_dir"], "00-fakey.error.json")
    assert error["delivery_fallback"] == "legacy"


def test_oversize_degrades_to_legacy(
    shadow_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Delivered text over max_bytes keeps the bundle and falls back."""
    monkeypatch.setattr(
        "sase.llm_provider.instruction_delivery.notify_instruction_fallback",
        lambda *args, **kwargs: None,
    )
    provider = _OversizeProvider("claude")
    invoke_with_instructions(
        provider,
        "hello",
        purpose="ordinary",
        artifacts_dir=shadow_env["artifacts_dir"],
        provider_name="claude",
        **_invoke_kwargs(),
    )
    manifest = _manifest(shadow_env["artifacts_dir"], "00-claude.json")
    assert manifest["delivery"]["status"] == "inherits_native"
    assert manifest["delivery"]["fallback"]["reason"] == "oversize"
    assert (
        Path(shadow_env["artifacts_dir"]) / INSTRUCTIONS_DIR_NAME / "00-claude.md"
    ).is_file()


def test_invalid_bundle_degrades_to_legacy(
    shadow_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A root bundle without the contract heading falls back."""
    from sase.instructions.compile import CompiledBundle, compile_bundle

    original = compile_bundle

    def _strip_contract(*args: Any, **kwargs: Any) -> CompiledBundle:
        compiled = original(*args, **kwargs)
        return CompiledBundle(
            text=compiled.text.replace("SASE Final Declaration", "Nope"),
            sections=compiled.sections,
            sha256=compiled.sha256,
            total_bytes=compiled.total_bytes,
            total_lines=compiled.total_lines,
            tokens_est=compiled.tokens_est,
            layers=compiled.layers,
            store_path=compiled.store_path,
            render_ms=compiled.render_ms,
            cache=compiled.cache,
        )

    monkeypatch.setattr("sase.instructions.compile.compile_bundle", _strip_contract)
    monkeypatch.setattr(
        "sase.llm_provider.instruction_delivery.notify_instruction_fallback",
        lambda *args, **kwargs: None,
    )
    provider = _ExplicitProvider("claude")
    invoke_with_instructions(
        provider,
        "hello",
        purpose="ordinary",
        artifacts_dir=shadow_env["artifacts_dir"],
        provider_name="claude",
        **_invoke_kwargs(),
    )
    manifest = _manifest(shadow_env["artifacts_dir"], "00-claude.json")
    assert manifest["delivery"]["fallback"]["reason"] == "invalid_bundle"
    assert manifest["delivery"]["status"] == "inherits_native"


def test_adapter_reported_delivery_failed_written_back(
    shadow_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Adapter fallback is rewritten onto the post-call manifest."""
    monkeypatch.setattr(
        "sase.llm_provider.instruction_delivery.notify_instruction_fallback",
        lambda *args, **kwargs: None,
    )
    provider = _AdapterFallbackProvider("claude")
    invoke_with_instructions(
        provider,
        "hello",
        purpose="ordinary",
        artifacts_dir=shadow_env["artifacts_dir"],
        provider_name="claude",
        **_invoke_kwargs(),
    )
    manifest = _manifest(shadow_env["artifacts_dir"], "00-claude.json")
    assert manifest["delivery"]["status"] == "inherits_native"
    assert manifest["delivery"]["fallback"]["reason"] == "delivery_failed"
    assert "adapter boom" in manifest["delivery"]["fallback"]["detail"]
    assert manifest["delivery"]["session_ids"] == ["sess-fail"]


def test_helper_render_failure_does_not_substitute_root(
    shadow_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed helper render leaves the root explicit and writes no helper files."""
    from sase.instructions.compile import compile_bundle
    from sase.instructions.facts import InstructionFacts

    original = compile_bundle

    def _fail_helper(facts: Any, **kwargs: Any) -> Any:
        parsed = facts if isinstance(facts, InstructionFacts) else facts
        actor = getattr(parsed, "actor", None) or (
            parsed.get("actor") if isinstance(parsed, dict) else None
        )
        if actor == "native_helper":
            raise RuntimeError("helper compile exploded")
        return original(facts, **kwargs)

    monkeypatch.setattr("sase.instructions.compile.compile_bundle", _fail_helper)
    monkeypatch.setattr(
        "sase.llm_provider.instruction_delivery.notify_instruction_fallback",
        lambda *args, **kwargs: None,
    )
    provider = _ExplicitProvider("claude")
    invoke_with_instructions(
        provider,
        "hello",
        purpose="ordinary",
        artifacts_dir=shadow_env["artifacts_dir"],
        provider_name="claude",
        **_invoke_kwargs(),
    )
    instructions = Path(shadow_env["artifacts_dir"]) / INSTRUCTIONS_DIR_NAME
    manifest = _manifest(shadow_env["artifacts_dir"], "00-claude.json")
    assert manifest["delivery"]["status"] == "explicit"
    assert manifest["delivery"]["subagent"]["status"] == "inherits_native"
    assert manifest["delivery"]["subagent"]["fallback"]["reason"] == "render_failed"
    assert list(instructions.glob("*.helper.*")) == []
    assert (instructions / "00-claude.md").is_file()


def test_no_artifacts_dir_has_no_active_delivery(
    shadow_env: dict[str, Any],
) -> None:
    """Without an artifacts dir there is no plan and no contextvar."""
    provider = _ExplicitProvider("claude")
    invoke_with_instructions(
        provider,
        "hello",
        purpose="ordinary",
        artifacts_dir=None,
        provider_name="claude",
        **_invoke_kwargs(),
    )
    assert provider.seen_delivery == [None]
    assert current_instruction_delivery() is None


def test_file_modes_are_0644(shadow_env: dict[str, Any]) -> None:
    """Root bundle and manifest files are mode 0644, not umask 0775."""
    provider = _FakeProvider()
    invoke_with_instructions(
        provider,
        "hello",
        purpose="ordinary",
        artifacts_dir=shadow_env["artifacts_dir"],
        provider_name="fakey",
        **_invoke_kwargs(),
    )
    instructions = Path(shadow_env["artifacts_dir"]) / INSTRUCTIONS_DIR_NAME
    assert _mode(instructions / "00-fakey.md") == 0o644
    assert _mode(instructions / "00-fakey.json") == 0o644


def test_notify_dedup_key_is_host_provider_reason_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fallback notifications share one dedup key per host/provider/reason/day."""
    from sase.llm_provider.instruction_delivery import notify_instruction_fallback

    upserts: list[Any] = []

    class _Path:
        def __str__(self) -> str:
            return "/tmp/notifications.jsonl"

    monkeypatch.setattr(
        "sase.notifications.store.notifications_file_path", lambda: _Path()
    )
    monkeypatch.setattr(
        "sase.llm_provider.instruction_delivery.best_effort_test_state_write_allowed",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        "sase.notifications.store.upsert_notification",
        lambda n, **kwargs: upserts.append(n),
    )
    notify_instruction_fallback("claude", "oversize", detail="too big")
    notify_instruction_fallback("claude", "oversize", detail="still too big")
    notify_instruction_fallback("claude", "provider_legacy")
    assert len(upserts) == 2
    assert upserts[0].dedup_key == upserts[1].dedup_key
    assert upserts[0].dedup_key.startswith("instructions:fallback:")
    assert ":claude:oversize:" in upserts[0].dedup_key


def test_materialize_writes_0600_and_unlinks(tmp_path: Path) -> None:
    """materialize yields a private 0600 file and removes it afterwards."""
    from sase.llm_provider.instruction_delivery import (
        ActiveInstructionDelivery,
        ActiveSlot,
        SlotPlan,
    )

    delivery = ActiveInstructionDelivery(
        invocation_id="inv-1",
        provider="claude",
        root=ActiveSlot(
            plan=SlotPlan(status="explicit", channel=CHANNEL_CLAUDE_ROOT),
            text="hello-bundle\n",
            sha256="a" * 64,
        ),
        subagent=ActiveSlot(plan=SlotPlan(status="none")),
    )
    held: Path | None = None
    with delivery.materialize("root") as path:
        assert path is not None
        held = path
        assert path.is_file()
        assert _mode(path) == 0o600
        assert path.read_text(encoding="utf-8") == "hello-bundle\n"
    assert held is not None
    assert not held.exists()


def test_delivered_text_appends_marker() -> None:
    """The marker is one trailing line and the regex matches it."""
    invocation_id = "00000000-0000-4000-8000-000000000042"
    text = delivered_text("hello\n", "abcdef1234567890", invocation_id)
    assert text.startswith("hello\n")
    match = MARKER_RE.search(text)
    assert match is not None
    assert match.group(1) == "abcdef123456"
    assert match.group(2) == invocation_id


def test_sase_owned_instruction_paths_are_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Managed project files and SASE home renders are included; others are not."""
    project, _ = make_roots(tmp_path)
    (project / "AGENTS.md").write_text("# project agents\n", encoding="utf-8")
    (project / "CLAUDE.md").write_text("# project claude\n", encoding="utf-8")
    home = tmp_path / "homeiso"
    home.mkdir()
    (home / "AGENTS.md").write_text(
        "## SASE Final Declaration\n\nHome contract.\n", encoding="utf-8"
    )
    (home / "CLAUDE.md").write_text("hand-written home file\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.llm_provider.instruction_delivery.Path.home",
        lambda *args: home,
    )
    owned = sase_owned_instruction_paths(project)
    assert (project / "AGENTS.md").resolve() in owned
    assert (project / "CLAUDE.md").resolve() in owned
    assert (home / "AGENTS.md").resolve() in owned
    assert (home / "CLAUDE.md").resolve() not in owned

    unmanaged = tmp_path / "unmanaged"
    unmanaged.mkdir()
    (unmanaged / "AGENTS.md").write_text("other\n", encoding="utf-8")
    owned_unmanaged = sase_owned_instruction_paths(unmanaged)
    assert (unmanaged / "AGENTS.md").resolve() not in owned_unmanaged
