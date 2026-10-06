"""Handler for ``sase instructions`` subcommands."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def handle_instructions_command(args: argparse.Namespace) -> None:
    """Dispatch to the appropriate ``sase instructions`` sub-handler."""
    sub = getattr(args, "instructions_subcommand", None) or "list"

    if sub == "list":
        from sase.amd.inventory import run_amd_list

        sys.exit(run_amd_list(args))

    if sub == "render":
        sys.exit(run_instructions_render(args))

    if sub == "verify":
        sys.exit(run_instructions_verify(args))

    print("Usage: sase instructions {list,render,verify}", file=sys.stderr)
    sys.exit(1)


def _resolve_project_root() -> Path:
    """Return the current project root (VCS top level, else cwd)."""
    cwd = Path.cwd()
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        result = None
    if result is not None and result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip())
    return cwd.resolve(strict=False)


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _latest_agent_run(agent: str) -> tuple[str, dict[str, Any]] | None:
    """Return ``(artifact_dir, agent_meta)`` for *agent*'s newest run."""
    from sase.instructions import _runs as run_mod

    scored = run_mod.enumerate_runs(
        limit_per_provider=200,
        since=None,
        until=None,
        project=None,
        agent=agent,
        providers=(),
    )
    if not scored:
        return None
    newest = max(scored, key=lambda run: run.started_at)
    meta = _read_json_file(Path(newest.artifact_dir) / "agent_meta.json")
    return newest.artifact_dir, meta


def _agent_base_facts(
    agent: str, *, project_root: Path
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Return ``(facts dict, recorded manifest or None)`` for *agent*.

    Prefers the agent's latest recorded instruction manifest when one is on
    disk; otherwise derives pre-E2 facts from ``agent_meta.json`` (provider
    from ``exec_llm_provider`` or ``llm_provider``, actor ``sase_root``,
    mode ``runtime``, purpose ``ordinary``).
    """
    from sase.instructions.facts import default_facts

    found = _latest_agent_run(agent)
    if found is None:
        raise _RenderError(f"unknown agent {agent!r}: no runs found")
    artifact_dir, meta = found
    recorded: dict[str, Any] | None = None
    instructions = meta.get("instructions")
    if isinstance(instructions, dict):
        latest = instructions.get("latest")
        if isinstance(latest, dict):
            manifest_rel = latest.get("manifest")
            if isinstance(manifest_rel, str) and manifest_rel:
                candidate = Path(artifact_dir) / manifest_rel
                manifest = _read_json_file(candidate)
                if manifest.get("facts") and manifest.get("bundle"):
                    recorded = manifest
    if recorded is not None and isinstance(recorded.get("facts"), dict):
        return dict(recorded["facts"]), recorded
    provider = meta.get("exec_llm_provider") or meta.get("llm_provider")
    if not provider:
        raise _RenderError(
            f"agent {agent!r} has no recorded provider in agent_meta.json"
        )
    facts = default_facts(project_root, provider=str(provider))
    return facts.to_dict(), None


class _RenderError(ValueError):
    """Raised when render arguments cannot be resolved."""


def _parse_fact_overrides(values: list[str]) -> dict[str, str]:
    """Parse repeatable ``KEY=VALUE`` (comma-separated accepted) overrides."""
    from sase.instructions.facts import FACT_NAMES

    pairs: dict[str, str] = {}
    for value in values or ():
        for chunk in str(value).split(","):
            text = chunk.strip()
            if not text:
                continue
            key, sep, item = text.partition("=")
            key = key.strip()
            item = item.strip()
            if not sep or not key or not item:
                raise _RenderError(
                    f"invalid --fact {chunk.strip()!r}; "
                    "expected KEY=VALUE with a non-empty value"
                )
            if key not in FACT_NAMES:
                raise _RenderError(
                    f"unknown fact {key!r}; valid facts: {', '.join(FACT_NAMES)}"
                )
            pairs[key] = item
    mode = pairs.get("mode")
    if mode in ("interactive", "export") and "actor" not in pairs:
        pairs["actor"] = "interactive"
    elif mode in ("interactive", "export") and pairs.get("actor") != "interactive":
        raise _RenderError(
            f"conflicting facts: mode {mode!r} requires actor 'interactive', "
            f"got {pairs['actor']!r}"
        )
    return pairs


def _changed_section_ids(
    recorded: dict[str, Any], fresh_sections: list[dict[str, Any]]
) -> list[str]:
    """Return section ids whose sha differs between manifests."""
    old = {
        str(section["id"]): section.get("sha256")
        for section in recorded.get("sections", [])
        if isinstance(section, dict) and "id" in section
    }
    new = {
        str(section["id"]): section.get("sha256")
        for section in fresh_sections
        if isinstance(section, dict) and "id" in section
    }
    changed = [
        section_id
        for section_id in sorted(set(old) | set(new))
        if old.get(section_id) != new.get(section_id)
    ]
    return changed


def run_instructions_render(args: argparse.Namespace) -> int:
    """Render the memory-built bundle preview and return the exit code."""
    import sys as _sys

    from sase.instructions.compile import compile_bundle
    from sase.instructions.facts import InstructionFactsError, parse_facts
    from sase.instructions.facts import default_facts as _default_facts
    from sase.instructions.manifest import build_manifest, preview_delivery
    from sase.instructions.parity import legacy_parity, render_parity_table

    project_root = _resolve_project_root()
    home_root = Path.home()
    agent = getattr(args, "agent", None)
    recorded: dict[str, Any] | None = None
    try:
        if agent is not None:
            base_facts, recorded = _agent_base_facts(
                str(agent), project_root=project_root
            )
        else:
            base_facts = _default_facts(project_root).to_dict()
        overrides = _parse_fact_overrides(list(getattr(args, "fact", []) or ()))
        merged = {**base_facts, **overrides}
        want_no_cache = bool(getattr(args, "no_cache", False))
        compiled = compile_bundle(
            merged,
            project_root=project_root,
            home_root=home_root,
            use_cache=not want_no_cache,
        )
        rendered_at = datetime.now(tz=UTC).isoformat()
        manifest = build_manifest(
            compiled,
            parse_facts(merged),
            preview_delivery(rendered_at=rendered_at),
        )
    except (_RenderError, InstructionFactsError) as exc:
        print(f"sase instructions render: {exc}", file=_sys.stderr)
        return 2
    except ValueError as exc:
        print(f"sase instructions render: {exc}", file=_sys.stderr)
        return 2

    common_digest = str(manifest["bundle"].get("common_digest") or "")
    included = [
        section for section in compiled.sections if section["status"] == "included"
    ]
    print(
        f"render {compiled.sha256[:12]} common={common_digest[:12]} "
        f"sections={len(included)} bytes={compiled.total_bytes} "
        f"tokens_est={compiled.tokens_est} cache={compiled.cache} "
        f"{compiled.render_ms:.1f}ms",
        file=_sys.stderr,
    )
    if agent is not None:
        recorded_sha = ""
        if recorded is not None:
            bundle = recorded.get("bundle")
            if isinstance(bundle, dict):
                recorded_sha = str(bundle.get("sha256") or "")
        if not recorded_sha:
            print(
                f"agent {agent}: no recorded bundle (pre-E2 run); "
                "rendered current sources",
                file=_sys.stderr,
            )
        elif recorded_sha == compiled.sha256:
            print(
                f"agent {agent}: bundle matches recorded {recorded_sha[:12]}",
                file=_sys.stderr,
            )
        else:
            assert recorded is not None
            changed = _changed_section_ids(recorded, list(compiled.sections))
            listed = ", ".join(changed) if changed else "no section detail"
            print(
                f"agent {agent}: bundle differs from recorded "
                f"{recorded_sha[:12]}: changed sections: {listed}",
                file=_sys.stderr,
            )

    parity_failed = False
    if bool(getattr(args, "parity", False)):
        from rich.console import Console

        report = legacy_parity(compiled, project_root, home_root)
        render_parity_table(report, console=Console(stderr=True))
        parity_failed = not report.ok

    if bool(getattr(args, "sections", False)):
        _render_sections_table(compiled)
    elif bool(getattr(args, "json", False)):
        print(json.dumps(manifest, indent=2, sort_keys=True))
    else:
        _sys.stdout.write(compiled.text)
    return 1 if parity_failed else 0


def _render_sections_table(compiled: Any) -> None:
    """Print the Rich section table for *compiled* to stdout."""
    from rich.console import Console
    from rich.table import Table

    table = Table("id", "layer", "status", "lifecycle", "bytes", "tokens_est", "source")
    for section in compiled.sections:
        if section["status"] == "included":
            status = "included"
            size = str(section.get("length", 0))
            tokens = str(section.get("tokens_est", 0))
        else:
            status = str(section.get("reason") or "excluded")
            size = "—"
            tokens = "0"
        sources = section.get("sources") or []
        if sources and isinstance(sources[0], dict):
            first = sources[0]
            source = f"{first.get('scope', '')}:{first.get('path', '')}"
        else:
            source = "—"
        table.add_row(
            str(section["id"]),
            str(section["layer"]),
            status,
            str(section.get("lifecycle", "neutral")),
            size,
            tokens,
            source,
        )
    Console().print(table)


def run_instructions_verify(args: argparse.Namespace) -> int:
    """Run the observed-mode scoreboard and render it."""
    from sase.instructions import _runs as run_mod
    from sase.instructions.render import (
        render_helper_rows,
        render_json,
        render_table,
    )
    from sase.instructions.verify import build_report, collect_observations

    limit = max(1, min(int(getattr(args, "limit", 20) or 20), 200))
    now = datetime.now(tz=UTC)
    since_raw = getattr(args, "since", "7d") or "7d"
    until_raw = getattr(args, "until", None)
    try:
        since = run_mod.parse_when(str(since_raw), now=now)
    except ValueError as exc:
        print(f"sase instructions verify: {exc}", file=sys.stderr)
        return 2
    try:
        until = (
            run_mod.parse_when(str(until_raw), now=now)
            if until_raw is not None
            else None
        )
    except ValueError as exc:
        print(f"sase instructions verify: {exc}", file=sys.stderr)
        return 2
    providers = tuple(getattr(args, "provider", []) or ())
    agent = getattr(args, "agent", None)
    want_json = bool(getattr(args, "json", False))
    want_helpers = bool(getattr(args, "helpers", False))

    scored = run_mod.enumerate_runs(
        limit_per_provider=limit,
        since=since,
        until=until,
        project=None,
        agent=agent,
        providers=providers,
    )
    observations = collect_observations(scored)
    filters: dict[str, object] = {
        "agent": agent,
        "helpers": want_helpers,
        "limit": limit,
        "providers": list(providers),
        "since": since.isoformat(),
        "until": until.isoformat() if until is not None else None,
    }
    report = build_report(scored, observations, filters=filters)
    include_observations = want_json and (agent is not None or want_helpers)
    if want_json:
        print(render_json(report, include_observations=include_observations))
        return 0
    render_table(report)
    if want_helpers:
        render_helper_rows(report)
    elif agent is not None:
        render_helper_rows(report)
    return 0


__all__ = [
    "handle_instructions_command",
    "run_instructions_render",
    "run_instructions_verify",
]
