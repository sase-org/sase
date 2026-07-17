"""CLI helpers for Agents-tab reproduction capture and replay."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .redact import redact_bundle
from .replay import ReproReplayResult, ReproReplayStepSnapshot, replay_agents_tab_bundle
from .schema import (
    AgentIdentity,
    ReproAppState,
    ReproAssertions,
    ReproBundle,
    ReproLoadState,
    ReproLoadStep,
    ReproManifest,
    ReproScreen,
    SCHEMA_VERSION,
    identity_to_json,
    load_bundle,
)
from .serialize import serialize_agent_rows

_BUNDLE_FILENAME = "agents_tab_repro.json"


def handle_repro_replay(args: argparse.Namespace) -> int:
    """Run ``sase repro replay`` and return a process exit code."""

    json_output = bool(getattr(args, "json", False))
    try:
        bundle_path = _resolve_bundle_path(Path(str(args.path)))
        size = _parse_size(str(getattr(args, "size", "120x40")))
        bundle = load_bundle(bundle_path)
        result = asyncio.run(replay_agents_tab_bundle(bundle, size=size))
        artifact_file_paths = _write_replay_artifacts(
            result.steps,
            _optional_path(getattr(args, "write_artifacts", None)),
        )
        payload = _replay_result_to_json(
            result,
            bundle_path=bundle_path,
            screen_paths=artifact_file_paths["screen_paths"],
            screenshot_paths=artifact_file_paths["screenshot_paths"],
        )
        if json_output:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            _print_replay_human(result, artifact_file_paths)

        assert_stable = bool(getattr(args, "assert_stable", False))
        return 0 if result.ok or not assert_stable else 1
    except Exception as exc:
        payload = _error_payload(
            path=str(getattr(args, "path", "")),
            error=str(exc),
        )
        if json_output:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"sase repro replay failed: {exc}", file=sys.stderr)
        return 1


def handle_repro_capture_agents_tab(args: argparse.Namespace) -> int:
    """Run ``sase repro capture agents-tab`` and return a process exit code."""

    json_output = bool(getattr(args, "json", False))
    try:
        size = _parse_size(str(getattr(args, "size", "120x40")))
        output_dir = Path(str(args.output))
        bundle_path = _capture_agents_tab_out_of_band(
            output_dir,
            commit_safe=bool(getattr(args, "commit_safe", True)),
            size=size,
        )
        payload: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "bundle_path": str(bundle_path),
            "result": "captured",
            "capture_mode": "out_of_band",
        }
        if json_output:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"captured out-of-band Agents-tab repro: {bundle_path}")
        return 0
    except Exception as exc:
        payload = _error_payload(
            path=str(getattr(args, "output", "")),
            error=str(exc),
        )
        payload["capture_mode"] = "out_of_band"
        if json_output:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"sase repro capture agents-tab failed: {exc}", file=sys.stderr)
        return 1


def _replay_result_to_json(
    result: ReproReplayResult,
    *,
    bundle_path: Path,
    screen_paths: list[str],
    screenshot_paths: list[str],
) -> dict[str, Any]:
    """Return the stable JSON shape for replay results."""

    return {
        "schema_version": result.bundle.manifest.schema_version,
        "bundle_path": str(bundle_path),
        "result": "passed" if result.ok else "failed",
        "verdict": result.verdict,
        "failed_invariants": [
            {
                "code": failure.code,
                "message": failure.message,
                "step_id": failure.step_id,
            }
            for failure in result.invariant_report.failures
        ],
        "state_steps": [_step_snapshot_to_json(step) for step in result.steps],
        "screen_paths": screen_paths,
        "screenshot_paths": screenshot_paths,
    }


def _capture_agents_tab_out_of_band(
    output_dir: str | Path,
    *,
    commit_safe: bool = True,
    size: tuple[int, int] = (120, 40),
) -> Path:
    """Capture current filesystem Agents-tab loader state without a live TUI."""

    from sase.ace.dismissed_agents import load_dismissed_agents
    from sase.ace.tui.actions.agents._loading_helpers import (
        load_agents_from_disk_with_state,
    )

    dismissed = load_dismissed_agents()
    steps: list[ReproLoadStep] = []
    for index, full_history in enumerate((False, True), start=1):
        load_result = load_agents_from_disk_with_state(
            set(dismissed),
            full_history=full_history,
        )
        rows = serialize_agent_rows(load_result.all_agents)
        identities = [row.identity for row in rows]
        steps.append(
            ReproLoadStep(
                step_id=f"out_of_band_{index:02d}",
                label=(
                    "out-of-band source-of-truth capture"
                    if full_history
                    else "out-of-band first-pass capture"
                ),
                load_state=_serialize_runtime_load_state(load_result.load_state),
                agent_rows=rows,
                app_state=ReproAppState(
                    visible_identities=identities,
                    selected_identity=identities[0] if identities else None,
                    dismissed_identities=[
                        _schema_identity(identity)
                        for identity in sorted(
                            dismissed,
                            key=lambda item: (
                                str(item[1]),
                                str(item[2]),
                                str(getattr(item[0], "value", item[0])),
                            ),
                        )
                    ],
                    flattened_parent_timestamps=[],
                    agents_seen_complete_history=bool(
                        load_result.load_state.complete_history
                    ),
                ),
                screen=ReproScreen(),
                metadata={
                    "capture_mode": "out_of_band",
                    "terminal_size": {"width": size[0], "height": size[1]},
                    "loaded_row_count": len(rows),
                    "dismissed_identity_count": len(dismissed),
                },
            )
        )

    bundle = ReproBundle(
        manifest=ReproManifest(
            schema_version=SCHEMA_VERSION,
            name=f"agents-tab-out-of-band-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
            created_at=datetime.now(UTC).isoformat(),
            source="out_of_band_filesystem_capture",
            commit_safe=commit_safe,
            description=(
                "capture_mode=out_of_band; uses current filesystem loader state "
                "and may miss transient prior TUI refreshes."
            ),
        ),
        load_steps=steps,
        assertions=ReproAssertions(),
    )
    if commit_safe:
        bundle = redact_bundle(bundle, commit_safe=True)

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    bundle_path = output / _BUNDLE_FILENAME
    bundle_path.write_text(
        json.dumps(bundle.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return bundle_path


def _resolve_bundle_path(path: Path) -> Path:
    if path.is_dir():
        return path / _BUNDLE_FILENAME
    return path


def _parse_size(value: str) -> tuple[int, int]:
    try:
        width_text, height_text = value.lower().split("x", maxsplit=1)
        width = int(width_text)
        height = int(height_text)
    except ValueError as exc:
        raise ValueError("size must be formatted as WIDTHxHEIGHT") from exc
    if width <= 0 or height <= 0:
        raise ValueError("size must use positive WIDTH and HEIGHT values")
    return (width, height)


def _optional_path(value: object) -> Path | None:
    if value is None:
        return None
    text = str(value)
    return None if not text else Path(text)


def _write_replay_artifacts(
    steps: list[ReproReplayStepSnapshot],
    output_dir: Path | None,
) -> dict[str, list[str]]:
    screen_paths: list[str] = []
    screenshot_paths: list[str] = []
    if output_dir is None:
        return {"screen_paths": screen_paths, "screenshot_paths": screenshot_paths}

    output_dir.mkdir(parents=True, exist_ok=True)
    for step in steps:
        safe_step_id = _safe_filename(step.step_id)
        screen_path = output_dir / f"{safe_step_id}.txt"
        screen_path.write_text(step.screen_text, encoding="utf-8")
        screen_paths.append(str(screen_path))

        svg_path = output_dir / f"{safe_step_id}.svg"
        svg_path.write_text(step.svg, encoding="utf-8")
        screenshot_paths.append(str(svg_path))
    return {"screen_paths": screen_paths, "screenshot_paths": screenshot_paths}


def _safe_filename(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in "._-" else "_" for char in value)
    return safe or "step"


def _step_snapshot_to_json(step: ReproReplayStepSnapshot) -> dict[str, Any]:
    return {
        "step_id": step.step_id,
        "visible_identities": [
            identity_to_json(identity) for identity in step.visible_identities
        ],
        "agents_with_children_identities": [
            identity_to_json(identity)
            for identity in step.agents_with_children_identities
        ],
        "selected_identity": (
            None
            if step.selected_identity is None
            else identity_to_json(step.selected_identity)
        ),
        "load_state": step.load_state,
        "agents_seen_complete_history": step.agents_seen_complete_history,
    }


def _print_replay_human(
    result: ReproReplayResult,
    artifact_file_paths: dict[str, list[str]],
) -> None:
    print(result.verdict)
    if result.invariant_report.failures:
        for failure in result.invariant_report.failures:
            print(f"{failure.code}: {failure.message}")
    if artifact_file_paths["screen_paths"] or artifact_file_paths["screenshot_paths"]:
        print(
            "wrote replay artifacts: "
            f"{len(artifact_file_paths['screen_paths'])} screens, "
            f"{len(artifact_file_paths['screenshot_paths'])} SVGs"
        )


def _error_payload(*, path: str, error: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "bundle_path": path,
        "result": "error",
        "failed_invariants": [],
        "state_steps": [],
        "screen_paths": [],
        "screenshot_paths": [],
        "error": error,
    }


def _serialize_runtime_load_state(load_state: Any) -> ReproLoadState:
    return ReproLoadState(
        tier=load_state.tier,
        complete_history=load_state.complete_history,
        complete_visible_inbox=load_state.complete_visible_inbox,
        artifact_source=load_state.artifact_source,
        used_artifact_index=load_state.used_artifact_index,
        index_error=load_state.index_error,
        repair_recommended=load_state.repair_recommended,
        repair_reason=load_state.repair_reason,
        truncated=load_state.truncated,
    )


def _schema_identity(identity: tuple[Any, str, str | None]) -> AgentIdentity:
    agent_type = identity[0]
    value = getattr(agent_type, "value", agent_type)
    if value not in ("run", "workflow"):
        value = str(value)
    return (value, identity[1], identity[2])  # type: ignore[return-value]
