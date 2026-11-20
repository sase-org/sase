"""Compile-time compaction of oversize provider root bundles (bundle_trim)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.feature_flags import override_flags
from sase.instructions.compaction import STEP_LIST_ROSTERS, STEP_SUPERSEDED_SUMMARIES
from sase.instructions.compile import CompiledBundle, compile_bundle
from sase.instructions.manifest import build_manifest, preview_delivery
from sase.llm_provider._instruction_boundary import (
    INSTRUCTIONS_DIR_NAME,
    invoke_with_instructions,
)
from sase.llm_provider.instruction_delivery import (
    CHANNEL_CLAUDE_ROOT,
    CHANNEL_CODEX_ROOT,
    current_instruction_delivery,
    delivered_text,
    provider_root_max_bytes,
)
from sase.llm_provider.types import InvokeResult
from tests.instructions.fixture_compiler import (
    core_note,
    make_facts,
    make_roots,
    web_descriptor,
    write,
)

#: Codex's declared root-slot cap.
CODEX_CAP = 32 * 1024

_FILLER = "keeps this fixture roster long enough to matter for the provider cap "


def delivered_bytes(bundle_text: str) -> int:
    """Return the size a launch measures: the bundle plus its marker line."""
    invocation_id = "00000000-0000-4000-8000-000000000000"
    return len(delivered_text(bundle_text, "f" * 64, invocation_id).encode("utf-8"))


@pytest.fixture(autouse=True)
def isolated_instructions_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the bundle store and render cache at a tmp dir."""
    home = tmp_path / "ihome"
    monkeypatch.setenv("SASE_INSTRUCTIONS_HOME", str(home))
    return home


def _strand(keyword: str, summary: str, *, superseded_by: str | None = None) -> str:
    if superseded_by is None:
        metadata = "metadata:\n  status: accepted\n"
    else:
        metadata = (
            "metadata:\n  status: superseded-in-part\n"
            f"  superseded_by: {superseded_by}\n"
        )
    return (
        f"---\nkeyword: {keyword}\nsummary: {summary}\n{metadata}---\n\n"
        "**Claim.** A test claim.\n"
    )


def _summary(index: int, repeats: int) -> str:
    return f"Rule {index} " + _FILLER * repeats


def _seed_web(
    project_root: Path,
    slug: str,
    *,
    accepted: int,
    superseded: int = 0,
    repeats: int = 8,
    superseded_repeats: int = 8,
) -> None:
    memory = project_root / "sase" / "memory"
    write(memory / f"{slug}.md", web_descriptor(slug.title(), f"{slug} web."))
    for index in range(accepted):
        write(
            memory / slug / f"keep-{index:02d}.md",
            _strand(f"Keep {slug} {index:02d}", _summary(index, repeats)),
        )
    for index in range(superseded):
        write(
            memory / slug / f"old-{index:02d}.md",
            _strand(
                f"Old {slug} {index:02d}",
                _summary(index, superseded_repeats),
                superseded_by="keep-00",
            ),
        )


def _section(compiled: CompiledBundle, section_id: str) -> dict[str, Any]:
    for section in compiled.sections:
        if section["id"] == section_id:
            return section
    raise AssertionError(f"missing section {section_id!r}")


def _compile(
    project_root: Path,
    home_root: Path,
    *,
    max_bytes: int | None,
    provider: str = "codex",
    use_cache: bool = False,
) -> CompiledBundle:
    return compile_bundle(
        make_facts(provider),
        project_root=project_root,
        home_root=home_root,
        use_cache=use_cache,
        max_bytes=max_bytes,
    )


def _superseded_heavy_roots(tmp_path: Path) -> tuple[Path, Path]:
    """A project whose superseded summaries push Codex over its cap."""
    project_root, home_root = make_roots(tmp_path)
    _seed_web(project_root, "decisions", accepted=10, superseded=40, repeats=1)
    return project_root, home_root


def test_superseded_summaries_step_brings_roster_under_cap(tmp_path: Path) -> None:
    project_root, home_root = _superseded_heavy_roots(tmp_path)
    uncapped = _compile(project_root, home_root, max_bytes=None)
    assert delivered_bytes(uncapped.text) > CODEX_CAP

    compiled = _compile(project_root, home_root, max_bytes=CODEX_CAP)

    assert delivered_bytes(compiled.text) <= CODEX_CAP
    assert compiled.compaction == {
        "step": STEP_SUPERSEDED_SUMMARIES,
        "max_bytes": CODEX_CAP,
        "uncompacted_bytes": uncapped.total_bytes,
    }
    decisions = _section(compiled, "proj.web.decisions")
    assert decisions["compaction"] == {
        "step": STEP_SUPERSEDED_SUMMARIES,
        "uncompacted_length": _section(uncapped, "proj.web.decisions")["length"],
    }
    assert "compaction" not in _section(compiled, "proj.web.task_types")
    assert "- Rule 3 keeps this fixture" in compiled.text  # accepted summaries stay
    assert "**Old decisions 03** (`old-03`) _[partly superseded by" in compiled.text
    assert "Summaries of superseded entries omitted" in compiled.text
    assert "`sase memory read decisions:<keyword>`" in compiled.text
    # Every section outside the compacted web is byte-identical.
    for section in uncapped.sections:
        if section["status"] == "included" and section["id"] != "proj.web.decisions":
            assert _section(compiled, section["id"])["sha256"] == section["sha256"]


def test_whole_list_rosters_compact_largest_first(tmp_path: Path) -> None:
    project_root, home_root = make_roots(tmp_path)
    _seed_web(project_root, "decisions", accepted=50, superseded=2, repeats=7)
    _seed_web(project_root, "notes", accepted=12, repeats=7)
    uncapped = _compile(project_root, home_root, max_bytes=None)
    assert delivered_bytes(uncapped.text) > CODEX_CAP

    compiled = _compile(project_root, home_root, max_bytes=CODEX_CAP)

    assert delivered_bytes(compiled.text) <= CODEX_CAP
    assert compiled.compaction is not None
    assert compiled.compaction["step"] == STEP_LIST_ROSTERS
    assert _section(compiled, "proj.web.decisions")["compaction"]["step"] == (
        STEP_LIST_ROSTERS
    )
    # The largest web was enough, so the smaller one keeps its summaries.
    assert "compaction" not in _section(compiled, "proj.web.notes")
    assert (
        _section(compiled, "proj.web.notes")["sha256"]
        == (_section(uncapped, "proj.web.notes")["sha256"])
    )
    assert "**Keep decisions 01** (`keep-01`)\n" in compiled.text
    assert "Entry summaries omitted to fit the provider budget" in compiled.text


def test_oversize_core_note_still_exceeds_cap(tmp_path: Path) -> None:
    project_root, home_root = make_roots(tmp_path)
    write(
        project_root / "sase" / "memory" / "huge.md",
        core_note("# Huge\n\n" + ("A core paragraph that cannot shrink. " * 1200)),
    )

    compiled = _compile(project_root, home_root, max_bytes=CODEX_CAP)

    assert delivered_bytes(compiled.text) > CODEX_CAP
    assert compiled.compaction is not None
    assert compiled.compaction["step"] == STEP_LIST_ROSTERS
    assert "compaction" not in _section(compiled, "proj.core.huge")
    # The one-strand fixture roster would grow with the omission note, so it
    # stays as compiled; only the larger generated roster shrinks.
    assert "compaction" not in _section(compiled, "proj.web.decisions")
    assert "compaction" in _section(compiled, "proj.web.task_types")
    for section in compiled.sections:
        if "compaction" in section:
            assert section["compaction"]["uncompacted_length"] > section["length"]


def test_under_cap_bundle_is_byte_identical(tmp_path: Path) -> None:
    project_root, home_root = make_roots(tmp_path)
    uncapped = _compile(project_root, home_root, max_bytes=None)
    capped = _compile(project_root, home_root, max_bytes=CODEX_CAP)

    assert capped.sha256 == uncapped.sha256
    assert capped.text == uncapped.text
    assert capped.sections == uncapped.sections
    assert capped.compaction is None
    manifest = build_manifest(capped, make_facts(), preview_delivery())
    assert "compaction" not in manifest["bundle"]
    assert all("compaction" not in section for section in manifest["sections"])


def test_uncapped_claude_render_is_unaffected(tmp_path: Path) -> None:
    project_root, home_root = _superseded_heavy_roots(tmp_path)
    compiled = _compile(project_root, home_root, max_bytes=None, provider="claude")

    assert compiled.compaction is None
    assert "omitted to fit" not in compiled.text
    assert "- Rule 3 keeps this fixture" in compiled.text


def test_compaction_is_deterministic(tmp_path: Path) -> None:
    project_root, home_root = _superseded_heavy_roots(tmp_path)
    first = _compile(project_root, home_root, max_bytes=CODEX_CAP)
    second = _compile(project_root, home_root, max_bytes=CODEX_CAP)
    assert first.sha256 == second.sha256
    assert first.compaction == second.compaction


def test_cached_uncompacted_bundle_is_never_served_to_capped_compile(
    tmp_path: Path,
) -> None:
    project_root, home_root = _superseded_heavy_roots(tmp_path)
    uncapped = _compile(project_root, home_root, max_bytes=None, use_cache=True)
    assert uncapped.cache == "miss"

    capped = _compile(project_root, home_root, max_bytes=CODEX_CAP, use_cache=True)
    assert capped.cache == "miss"
    assert capped.sha256 != uncapped.sha256

    again = _compile(project_root, home_root, max_bytes=CODEX_CAP, use_cache=True)
    assert again.cache == "hit"
    assert again.sha256 == capped.sha256
    assert again.compaction == capped.compaction
    assert again.sections == capped.sections


def test_manifest_records_compaction(tmp_path: Path) -> None:
    project_root, home_root = _superseded_heavy_roots(tmp_path)
    compiled = _compile(project_root, home_root, max_bytes=CODEX_CAP)

    manifest = build_manifest(compiled, make_facts(), preview_delivery())

    assert manifest["bundle"]["compaction"] == compiled.compaction
    compacted = [s["id"] for s in manifest["sections"] if "compaction" in s]
    assert compacted == ["proj.web.decisions"]


def test_provider_root_max_bytes_follows_declared_caps() -> None:
    assert provider_root_max_bytes("claude") is None
    assert provider_root_max_bytes("no-such-provider") is None
    with override_flags(codex_explicit_instructions=True):
        assert provider_root_max_bytes("codex") == CODEX_CAP
    with override_flags(codex_explicit_instructions=False):
        assert provider_root_max_bytes("codex") is None


class _CappedProvider:
    """Explicit-root provider double with an optional root byte cap."""

    def __init__(self, name: str, channel: str, max_bytes: int | None) -> None:
        self._name = name
        self._channel = channel
        self._max_bytes = max_bytes
        self.delivered: list[str | None] = []

    def provider_name(self) -> str:
        return self._name

    def resolve_model_name(self, model_tier: str = "large") -> str:
        return f"{self._name}-{model_tier}"

    def instruction_delivery(self) -> dict[str, Any]:
        root: dict[str, Any] = {"status": "explicit", "channel": self._channel}
        if self._max_bytes is not None:
            root["max_bytes"] = self._max_bytes
        return {"root": root, "subagent": {"status": "inherits_root"}}

    def invoke(self, prompt: str, **kwargs: Any) -> InvokeResult:
        delivery = current_instruction_delivery()
        self.delivered.append(
            None
            if delivery is None or delivery.root.plan.status != "explicit"
            else delivery.root.text
        )
        return InvokeResult(content="fake-reply", usage=None)


def _launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    project_root: Path,
    provider: _CappedProvider,
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"exec_llm_provider": provider.provider_name()}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_ACTIVE_PROJECT_DIR", str(project_root))
    monkeypatch.setenv("SASE_AGENT_NAME", "compaction-test-agent")
    monkeypatch.delenv("SASE_INSTRUCTIONS_FILE", raising=False)
    notified: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "sase.llm_provider.instruction_delivery.notify_instruction_fallback",
        lambda provider, reason, **_: notified.append((provider, reason)),
    )
    invoke_with_instructions(
        provider,
        "hello",
        purpose="ordinary",
        artifacts_dir=str(artifacts_dir),
        provider_name=provider.provider_name(),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        options=None,
    )
    manifest_path = (
        artifacts_dir / INSTRUCTIONS_DIR_NAME / f"00-{provider.provider_name()}.json"
    )
    return json.loads(manifest_path.read_text(encoding="utf-8")), notified


def test_capped_launch_delivers_compacted_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root, _home_root = _superseded_heavy_roots(tmp_path)
    provider = _CappedProvider("codex", CHANNEL_CODEX_ROOT, CODEX_CAP)

    manifest, notified = _launch(tmp_path, monkeypatch, project_root, provider)

    assert notified == []
    assert manifest["delivery"]["status"] == "explicit"
    assert manifest["bundle"]["compaction"]["step"] == STEP_SUPERSEDED_SUMMARIES
    (delivered,) = provider.delivered
    assert delivered is not None
    assert len(delivered.encode("utf-8")) <= CODEX_CAP
    assert "Summaries of superseded entries omitted" in delivered


def test_capped_launch_still_falls_back_when_compaction_cannot_fit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root, _home_root = make_roots(tmp_path)
    write(
        project_root / "sase" / "memory" / "huge.md",
        core_note("# Huge\n\n" + ("A core paragraph that cannot shrink. " * 1200)),
    )
    provider = _CappedProvider("codex", CHANNEL_CODEX_ROOT, CODEX_CAP)

    manifest, notified = _launch(tmp_path, monkeypatch, project_root, provider)

    assert notified == [("codex", "oversize")]
    assert manifest["delivery"]["status"] == "inherits_native"
    assert manifest["delivery"]["fallback"]["reason"] == "oversize"
    assert provider.delivered == [None]


def test_uncapped_launch_delivers_full_rosters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root, _home_root = _superseded_heavy_roots(tmp_path)
    provider = _CappedProvider("claude", CHANNEL_CLAUDE_ROOT, None)

    manifest, notified = _launch(tmp_path, monkeypatch, project_root, provider)

    assert notified == []
    assert manifest["delivery"]["status"] == "explicit"
    assert "compaction" not in manifest["bundle"]
    (delivered,) = provider.delivered
    assert delivered is not None
    assert "omitted to fit" not in delivered
    assert "- Rule 3 keeps this fixture" in delivered
