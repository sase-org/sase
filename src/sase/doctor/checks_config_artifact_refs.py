"""Artifact-reference config checks for ``sase doctor``."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.config.artifact_ref_files import parse_artifact_file_root
from sase.diagnostics import CheckStatus, DiagnosticCheck
from sase.doctor.checks_config_common import MAX_DETAIL_ROWS


def check_config_artifact_refs() -> DiagnosticCheck:
    """Surface unusable ``artifact_refs.file.roots`` entries."""

    from sase.config.core import load_config_layers

    problems: list[dict[str, str]] = []
    parsed: list[tuple[str, Path, str]] = []
    seen_names: dict[str, str] = {}
    saw_artifact_refs = False
    usable_count = 0
    for layer in load_config_layers():
        if not layer.exists or "artifact_refs" not in layer.data:
            continue
        saw_artifact_refs = True
        source = str(layer.path or layer.name)
        raw_artifact_refs = layer.data.get("artifact_refs")
        raw_roots = _raw_file_roots(raw_artifact_refs)
        if raw_roots is None:
            problems.append(
                _problem(
                    source,
                    "artifact_refs.file.roots must be a list of root mappings",
                )
            )
            continue
        for index, item in enumerate(raw_roots):
            key = f"artifact_refs.file.roots[{index}]"
            try:
                root = parse_artifact_file_root(item, source_layer=layer.name)
            except ValueError as exc:
                problems.append(_problem(source, f"{key}: {exc}"))
                continue
            previous_source = seen_names.get(root.name)
            if previous_source is not None:
                problems.append(
                    _problem(
                        source,
                        f"{key}: duplicate root name {root.name!r}; "
                        f"previously supplied by {previous_source}",
                    )
                )
            seen_names[root.name] = source
            if not root.path.exists():
                problems.append(_problem(source, f"{key}: {root.path} is missing"))
            elif not root.path.is_dir():
                problems.append(
                    _problem(source, f"{key}: {root.path} is not a directory")
                )
            else:
                usable_count += 1
            parsed.append((root.name, root.path, source))

    problems.extend(_nested_root_problems(parsed))
    if saw_artifact_refs and usable_count == 0:
        problems.append(
            {
                "source": "artifact_refs",
                "message": (
                    "artifact_refs.file.roots parsed to zero usable existing "
                    "directories"
                ),
            }
        )

    status: CheckStatus = "WARN" if problems else "OK"
    return DiagnosticCheck(
        id="config.artifact_refs",
        group="config",
        status=status,
        title="Artifact reference config",
        summary=(
            f"{len(problems)} artifact reference config issue(s) found"
            if problems
            else "artifact reference config is usable"
        ),
        details=tuple(row["message"] for row in problems)[:MAX_DETAIL_ROWS],
        next_steps=(
            (
                "Fix artifact_refs.file.roots in the named config file(s), "
                "then rerun `sase doctor -C config.artifact_refs`.",
            )
            if problems
            else ()
        ),
        data={"problems": problems},
    )


def _raw_file_roots(raw_artifact_refs: object) -> list[object] | None:
    if not isinstance(raw_artifact_refs, Mapping):
        return None
    raw_file = raw_artifact_refs.get("file")
    if raw_file is None:
        return []
    if not isinstance(raw_file, Mapping):
        return None
    raw_roots = raw_file.get("roots")
    if raw_roots is None:
        return []
    return raw_roots if isinstance(raw_roots, list) else None


def _nested_root_problems(
    roots: list[tuple[str, Path, str]],
) -> list[dict[str, str]]:
    problems: list[dict[str, str]] = []
    for index, (name, path, source) in enumerate(roots):
        for other_name, other_path, _other_source in roots[:index]:
            if path == other_path:
                continue
            if _is_nested(path, other_path):
                problems.append(
                    _problem(
                        source,
                        f"artifact_refs.file.roots: root {name!r} is nested "
                        f"inside root {other_name!r}",
                    )
                )
            elif _is_nested(other_path, path):
                problems.append(
                    _problem(
                        source,
                        f"artifact_refs.file.roots: root {other_name!r} is "
                        f"nested inside root {name!r}",
                    )
                )
    return problems


def _is_nested(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return path != parent


def _problem(source: str, message: str) -> dict[str, str]:
    return {"source": source, "message": f"{source}: {message}"}


__all__ = ["check_config_artifact_refs"]
