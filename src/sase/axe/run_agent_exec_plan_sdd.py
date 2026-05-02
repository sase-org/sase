"""SDD plan-reference helpers for agent execution plans."""

from __future__ import annotations

import logging
import os
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any


def commit_sdd_files_for_exec_plan(
    workspace_dir: str,
    plan_name: str,
    *,
    plan_kind: str = "tales",
    logger: logging.Logger,
    subprocess_run: Callable[..., Any],
) -> None:
    """Commit SDD prompt and plan files via ``sase commit`` before launching the epic agent.

    The ``#gh`` workflow pre-step runs ``git checkout . && git clean -fd`` which
    wipes uncommitted files.  Committing (and pushing) the SDD files first
    ensures the epic agent can still read them.
    """
    from sase.sdd.files import find_sdd_file

    base = Path(workspace_dir)
    fname = f"{plan_name}.md"
    prompt_found = find_sdd_file(base, "prompts", fname)
    plan_found = find_sdd_file(base, plan_kind, fname)
    files = [str(f) for f in (prompt_found, plan_found) if f is not None]
    if not files:
        return
    message = f"chore: Add SDD prompt and plan for {plan_name}"
    # -M / --message-file expects a file path, not a raw string.
    # handle_commit_command deletes the file after reading it.
    msg_fd, msg_path = tempfile.mkstemp(suffix=".txt", prefix="sase_sdd_msg_")
    try:
        os.write(msg_fd, message.encode())
    finally:
        os.close(msg_fd)
    cmd = ["sase", "commit", "-M", msg_path]
    for f in files:
        cmd.extend(["-f", f])
    result = subprocess_run(
        cmd,
        cwd=workspace_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        logger.warning(
            "sase commit for SDD files failed (exit %d): %s",
            result.returncode,
            result.stderr,
        )


def build_sdd_plan_ref(
    *,
    sdd_plan_path: Path | None,
    sdd_dir: Path,
    workspace_dir: str,
    sdd_plan_name: str | None,
    version_controlled: bool,
    fallback_plan_file: str,
    plan_kind: str,
) -> str:
    """Build the plan reference passed to a plan-container creation xprompt."""
    if sdd_plan_path and sdd_plan_path.exists():
        if version_controlled:
            try:
                return sdd_plan_path.relative_to(Path(workspace_dir)).as_posix()
            except ValueError:
                return sdd_plan_path.as_posix()

        try:
            sdd_relative = sdd_plan_path.relative_to(sdd_dir)
            return (Path(".sase") / "sdd" / sdd_relative).as_posix()
        except ValueError:
            try:
                return sdd_plan_path.relative_to(Path(workspace_dir)).as_posix()
            except ValueError:
                return sdd_plan_path.as_posix()

    from sase.sdd.files import get_yyyymm

    yyyymm = get_yyyymm()
    if sdd_plan_name and not version_controlled:
        return f".sase/sdd/{plan_kind}/{yyyymm}/{sdd_plan_name}.md"
    if sdd_plan_name:
        return f"sdd/{plan_kind}/{yyyymm}/{sdd_plan_name}.md"
    return fallback_plan_file


def build_epic_plan_ref(
    *,
    sdd_plan_path: Path | None,
    sdd_dir: Path,
    workspace_dir: str,
    sdd_plan_name: str | None,
    version_controlled: bool,
    fallback_plan_file: str,
) -> str:
    """Build the plan reference passed to the epic-creation xprompt."""
    return build_sdd_plan_ref(
        sdd_plan_path=sdd_plan_path,
        sdd_dir=sdd_dir,
        workspace_dir=workspace_dir,
        sdd_plan_name=sdd_plan_name,
        version_controlled=version_controlled,
        fallback_plan_file=fallback_plan_file,
        plan_kind="epics",
    )


_SDD_LEGEND_REF_RE = re.compile(
    r"(?P<path>(?:\.sase/)?sdd/legends/[A-Za-z0-9_./~+-]+\.md)"
)


def _read_markdown_frontmatter(path: Path) -> tuple[dict[str, Any], str] | None:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None

    from sase.sdd.frontmatter import parse_frontmatter

    frontmatter, body, _ = parse_frontmatter(content)
    return frontmatter, body


def _frontmatter_legend_bead_id(frontmatter: dict[str, Any]) -> str | None:
    value = frontmatter.get("legend_bead_id")
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _resolve_sdd_reference_path(
    ref: str,
    *,
    workspace_dir: str,
    sdd_dir: Path | None,
) -> Path | None:
    ref_path = Path(ref).expanduser()
    if ref_path.is_absolute():
        return ref_path if ref_path.exists() else None

    candidates: list[Path] = [Path(workspace_dir) / ref_path]
    if sdd_dir is not None:
        for prefix in (Path(".sase") / "sdd", Path("sdd")):
            try:
                candidates.append(sdd_dir / ref_path.relative_to(prefix))
            except ValueError:
                pass
        candidates.append(sdd_dir / ref_path)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _iter_sdd_legend_refs(*texts: str) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for match in _SDD_LEGEND_REF_RE.finditer(text):
            ref = match.group("path")
            if ref not in seen:
                refs.append(ref)
                seen.add(ref)
    return refs


def infer_epic_legend_bead_id(
    *,
    sdd_plan_path: Path | None,
    workspace_dir: str,
    sdd_dir: Path | None,
) -> str | None:
    """Infer an epic's parent legend bead ID from SDD metadata when safe."""
    if sdd_plan_path is None:
        return None

    parsed_plan = _read_markdown_frontmatter(sdd_plan_path)
    if parsed_plan is None:
        return None

    plan_frontmatter, plan_body = parsed_plan
    direct_id = _frontmatter_legend_bead_id(plan_frontmatter)
    if direct_id:
        return direct_id

    reference_texts = [plan_body]
    prompt_ref = plan_frontmatter.get("prompt")
    if prompt_ref:
        prompt_path = _resolve_sdd_reference_path(
            str(prompt_ref),
            workspace_dir=workspace_dir,
            sdd_dir=sdd_dir,
        )
        if prompt_path is not None:
            try:
                reference_texts.append(prompt_path.read_text(encoding="utf-8"))
            except OSError:
                pass

    legend_ids: set[str] = set()
    for legend_ref in _iter_sdd_legend_refs(*reference_texts):
        legend_path = _resolve_sdd_reference_path(
            legend_ref,
            workspace_dir=workspace_dir,
            sdd_dir=sdd_dir,
        )
        if legend_path is None:
            continue
        parsed_legend = _read_markdown_frontmatter(legend_path)
        if parsed_legend is None:
            continue
        legend_id = _frontmatter_legend_bead_id(parsed_legend[0])
        if legend_id:
            legend_ids.add(legend_id)

    if len(legend_ids) == 1:
        return next(iter(legend_ids))
    return None


def plan_kind_for_action(action: str) -> str:
    if action == "epic":
        return "epics"
    if action == "legend":
        return "legends"
    return "tales"


def build_saved_plan_ref(
    *,
    sdd_plan_path: Path | None,
    sdd_dir: Path,
    workspace_dir: str,
    version_controlled: bool,
    fallback_plan_file: str,
) -> str:
    """Build the plan reference passed to a normal coder follow-up."""
    if sdd_plan_path and sdd_plan_path.exists():
        if version_controlled:
            try:
                return sdd_plan_path.relative_to(Path(workspace_dir)).as_posix()
            except ValueError:
                return sdd_plan_path.as_posix()

        try:
            sdd_relative = sdd_plan_path.relative_to(sdd_dir)
            return (Path(".sase") / "sdd" / sdd_relative).as_posix()
        except ValueError:
            return sdd_plan_path.as_posix()

    return fallback_plan_file
