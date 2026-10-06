"""Deterministic shadow artifacts for scoreboard coverage tests.

Each fixture holds a manifest and bundle laid out exactly as the
invocation boundary writes them (``NN-<provider>.md`` /
``NN-<provider>.json``). Manifests follow the v1 wire shape from the epic
plan (decision 8) with self-consistent offsets, section digests, bundle
digests, and ``common_digest`` computed over the real bundle bytes, so
coverage matching and section diffs exercise genuine wire-shaped output.
Only ``rendered_at`` (and the delivery identity) is caller-supplied for
deterministic ordering tests.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from pathlib import Path
from typing import Any


def _fixture_section_rows(
    provider: str,
) -> tuple[tuple[str, str, str, bool, bool, str], ...]:
    """Return included fixture sections in bundle order for *provider*."""
    return (
        (
            "frame.title",
            "frame",
            "neutral",
            True,
            False,
            "# Fixture Agent Instructions\n",
        ),
        (
            "pkg.sase.memory",
            "package",
            "neutral",
            False,
            False,
            "#### SASE Memory\n\nThe packaged memory contract.\n",
        ),
        (
            "pkg.root.final_declaration",
            "package",
            "root",
            True,
            False,
            "#### SASE Final Declaration\n\nOnly the root agent submits.\n",
        ),
        (
            f"pkg.provider.{provider}",
            "package",
            "root",
            False,
            True,
            f"#### {provider.title()} Single-Turn Instructions\n\n"
            "Provider directive body.\n",
        ),
        (
            "home.core.gotchas",
            "home",
            "neutral",
            False,
            False,
            "### Gotchas (gotchas)\n\nHome gotchas body.\n",
        ),
        (
            "proj.core.gotchas",
            "project",
            "neutral",
            False,
            False,
            "### Gotchas (gotchas)\n\nProject gotchas body.\n",
        ),
    )


def _section_bytes(text: str) -> bytes:
    return (text.rstrip("\n") + "\n\n").encode("utf-8")


def _tokens_est(text: str) -> int:
    return math.ceil(len(text) / 4)


def fixture_bundle(
    provider: str = "codex",
) -> tuple[str, list[dict[str, Any]]]:
    """Return ``(bundle_text, sections)`` with contiguous wire offsets."""
    parts: list[str] = []
    sections: list[dict[str, Any]] = []
    offset = 0
    for (
        section_id,
        layer,
        lifecycle,
        required,
        provider_specific,
        body,
    ) in _fixture_section_rows(provider):
        data = _section_bytes(body)
        text = data.decode("utf-8")
        parts.append(text)
        sections.append(
            {
                "id": section_id,
                "layer": layer,
                "status": "included",
                "lifecycle": lifecycle,
                "required": required,
                "provider_specific": provider_specific,
                "offset": offset,
                "length": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "tokens_est": _tokens_est(text),
                "sources": [
                    {
                        "scope": (
                            "package"
                            if layer == "package"
                            else ("home" if layer == "home" else layer)
                        ),
                        "kind": "memory_note",
                        "path": f"sase/memory/{section_id.rsplit('.', 1)[-1]}.md",
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                ],
            }
        )
        offset += len(data)
    sections.append(
        {
            "id": "pkg.helper.contract",
            "layer": "package",
            "status": "excluded",
            "lifecycle": "helper",
            "required": True,
            "provider_specific": False,
            "tokens_est": 0,
            "sources": [
                {
                    "scope": "package",
                    "kind": "helper_template",
                    "path": "templates/claude_helper_instructions.md",
                }
            ],
            "reason": "overlay",
        }
    )
    return "".join(parts), sections


def fixture_manifest(
    bundle_text: str,
    sections: list[dict[str, Any]],
    *,
    provider: str = "codex",
    purpose: str = "ordinary",
    rendered_at: str = "2026-10-06T12:00:00Z",
    seq: int = 0,
    agent_name: str = "coverage-test-agent",
    render_ms: float = 12.5,
    cache: str = "miss",
) -> dict[str, Any]:
    """Return a wire-shaped v1 manifest for *bundle_text*/*sections*."""
    bundle_blob = bundle_text.encode("utf-8")
    common_pairs = [
        [section["id"], section["sha256"]]
        for section in sections
        if section["status"] == "included" and not section["provider_specific"]
    ]
    canonical = json.dumps(common_pairs, sort_keys=True, separators=(",", ":"))
    common_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    by_layer: dict[str, dict[str, int]] = {}
    for section in sections:
        if section["status"] != "included":
            continue
        totals = by_layer.setdefault(section["layer"], {"bytes": 0, "tokens_est": 0})
        totals["bytes"] += section["length"]
        totals["tokens_est"] += section["tokens_est"]
    return {
        "schema_version": 1,
        "compiler": {
            "name": "sase-instructions",
            "version": 1,
            "sase_version": "0.0-test",
        },
        "facts": {
            "actor": "sase_root",
            "mode": "runtime",
            "purpose": purpose,
            "provider": provider,
            "project": "fixture",
            "host": "testhost",
            "vcs": None,
        },
        "bundle": {
            "sha256": hashlib.sha256(bundle_blob).hexdigest(),
            "common_digest": common_digest,
            "bytes": len(bundle_blob),
            "lines": bundle_text.count("\n"),
            "tokens_est": _tokens_est(bundle_text),
            "store_path": "/tmp/fixture-store/bundle.md",
        },
        "budget": {"by_layer": by_layer},
        "sections": sections,
        "delivery": {
            "status": "shadow",
            "channel": None,
            "invocation_id": str(uuid.uuid4()),
            "invocation_seq": seq,
            "attempt": 1,
            "agent_name": agent_name,
            "agent_type": "editor",
            "model": "",
            "parent_invocation_id": None,
            "session_ids": [],
            "provider_cli_version": None,
            "rendered_at": rendered_at,
            "render_ms": render_ms,
            "cache": cache,
        },
        "observation": {"status": "unobserved"},
    }


def write_shadow_run(
    base: Path,
    *,
    provider: str = "codex",
    purpose: str = "ordinary",
    rendered_at: str = "2026-10-06T12:00:00Z",
    seq: int = 0,
    agent_name: str = "coverage-test-agent",
    render_ms: float = 12.5,
    cache: str = "miss",
    artifacts_dir: Path | None = None,
) -> tuple[Path, dict[str, Any], str]:
    """Write one shadow run dir; return ``(artifacts_dir, manifest, bundle)``."""
    bundle_text, sections = fixture_bundle(provider)
    manifest = fixture_manifest(
        bundle_text,
        sections,
        provider=provider,
        purpose=purpose,
        rendered_at=rendered_at,
        seq=seq,
        agent_name=agent_name,
        render_ms=render_ms,
        cache=cache,
    )
    if artifacts_dir is None:
        artifacts_dir = base / f"run-{provider}-{purpose}-{seq}"
    instructions_dir = artifacts_dir / "instructions"
    instructions_dir.mkdir(parents=True, exist_ok=True)
    (instructions_dir / f"{seq:02d}-{provider}.md").write_text(
        bundle_text, encoding="utf-8"
    )
    (instructions_dir / f"{seq:02d}-{provider}.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return artifacts_dir, manifest, bundle_text


def write_real_shadow_run(
    base: Path,
    *,
    provider: str = "codex",
    purpose: str = "ordinary",
    rendered_at: str = "2026-10-06T12:00:00Z",
    seq: int = 0,
    agent_name: str = "coverage-test-agent",
    use_cache: bool = False,
    artifacts_dir: Path | None = None,
) -> tuple[Path, dict[str, Any], str]:
    """Write one shadow run via the real compiler and manifest assembler.

    Uses :func:`compile_bundle` and :func:`build_manifest` against fixture
    project/home roots. The caller must point ``SASE_INSTRUCTIONS_HOME`` at
    a tmp dir (the bundle store and render cache live there).
    """
    import uuid as _uuid

    from sase.instructions.compile import compile_bundle
    from sase.instructions.manifest import build_manifest
    from tests.instructions.fixture_compiler import make_facts, make_roots

    project_root, home_root = make_roots(base / f"real-roots-{provider}-{seq}")
    facts = make_facts(provider, purpose=purpose)
    compiled = compile_bundle(
        facts, project_root=project_root, home_root=home_root, use_cache=use_cache
    )
    manifest = build_manifest(
        compiled,
        facts,
        {
            "status": "shadow",
            "channel": None,
            "invocation_id": str(_uuid.uuid4()),
            "invocation_seq": seq,
            "attempt": 1,
            "agent_name": agent_name,
            "agent_type": "editor",
            "model": "",
            "parent_invocation_id": None,
            "session_ids": [],
            "provider_cli_version": None,
            "rendered_at": rendered_at,
        },
    )
    if artifacts_dir is None:
        artifacts_dir = base / f"real-run-{provider}-{purpose}-{seq}"
    instructions_dir = artifacts_dir / "instructions"
    instructions_dir.mkdir(parents=True, exist_ok=True)
    (instructions_dir / f"{seq:02d}-{provider}.md").write_text(
        compiled.text, encoding="utf-8"
    )
    (instructions_dir / f"{seq:02d}-{provider}.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return artifacts_dir, manifest, compiled.text


def write_shadow_error(
    artifacts_dir: Path, *, provider: str = "codex", seq: int = 1
) -> Path:
    """Write a minimal ``.error.json`` shadow failure record."""
    path = artifacts_dir / "instructions" / f"{seq:02d}-{provider}.error.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provider": provider,
                "purpose": "ordinary",
                "invocation_seq": seq,
                "error": {"type": "RuntimeError", "message": "synthetic boom"},
                "rendered_at": "2026-10-06T12:05:00Z",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


__all__ = [
    "fixture_bundle",
    "fixture_manifest",
    "write_real_shadow_run",
    "write_shadow_error",
    "write_shadow_run",
]
