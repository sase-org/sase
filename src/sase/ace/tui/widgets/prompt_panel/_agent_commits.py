"""Agent-specific commit helpers for the prompt panel header."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from rich.text import Text

from sase.external_repos import external_repo_name_from_clone_parts
from sase.linked_repos import EXTERNAL_REPO_CLONES_SUBDIR
from sase.plan_documents import PlanWorkspace
from sase.project_display_names import project_display_name_for
from sase.repo_inventory import RepoKind

from ...models.agent import Agent
from ._agent_context_common import (
    COLOR_EXTERNAL_REPO_GLYPH,
    COLOR_EXTERNAL_REPO_NAME,
    COLOR_WORKSPACE_GLYPH,
    COLOR_WORKSPACE_NAME,
    EXTERNAL_REPO_GLYPH,
    WORKSPACE_GLYPH,
)

if TYPE_CHECKING:
    from ._agent_display_state import CommitViewSpec, HeaderHintState

_COLOR_COMMIT_SHA = "dim #D7D7AF"
_COLOR_COMMIT_SUBJECT = "#D7D7FF"


@dataclass(frozen=True)
class _CommitInfo:
    """Compact display data for one commit."""

    short_sha: str
    subject: str


@dataclass(frozen=True)
class _CommitLine:
    """Rendered commit row plus optional view-target metadata."""

    short_sha: str
    subject: str
    view_spec: CommitViewSpec


@dataclass(frozen=True)
class CommitDiffInfo:
    """Per-commit diff metadata used by TUI diff/delta surfaces."""

    repo_name: str
    short_sha: str
    subject: str
    diff_path: str
    is_primary: bool
    repo_kind: RepoKind = "linked"
    workspace_dir: str = ""


@dataclass(frozen=True)
class _AgentCommitGroup:
    """Ordered commit rows attributed to one repository."""

    repo_name: str
    repo_kind: RepoKind
    commits: tuple[_CommitLine, ...]


class _RepoAttribution(NamedTuple):
    name: str
    kind: RepoKind
    workspace_dir: str


def _display_text(value: object) -> str:
    return str(value).strip()


def _first_subject_line(message: str) -> str:
    for line in message.splitlines():
        subject = line.strip()
        if subject:
            return subject
    return ""


def _short_sha(value: str) -> str:
    return value.split()[0][:12] if value.split() else ""


def _full_sha(value: object) -> str:
    text = _display_text(value)
    return text.split()[0] if text.split() else ""


def _agent_plan_workspaces(agent: Agent) -> tuple[PlanWorkspace, ...]:
    """Return owner identity without doing storage resolution on the UI path."""
    if not agent.workspace_dir:
        return ()
    project = Path(agent.project_file).parent.name if agent.project_file else None
    return (
        PlanWorkspace(
            workspace_dir=agent.workspace_dir,
            workspace_num=agent.effective_workspace_num or 1,
            project=project,
        ),
    )


def _primary_repo_name(agent: Agent, step_output: dict[str, Any] | None) -> str:
    meta_project = step_output.get("meta_project") if step_output is not None else None
    if meta_project:
        return project_display_name_for(_display_text(meta_project))
    if agent.project_display_name:
        return agent.project_display_name
    if agent.project_file:
        key = Path(agent.project_file).stem
        if key:
            return project_display_name_for(key)
    return "primary"


def _legacy_commit_diff_path(
    agent: Agent,
    step_output: dict[str, Any] | None,
) -> str | None:
    raw_path: object = None
    if step_output is not None:
        raw_path = step_output.get("diff_path") or step_output.get("commit_diff_path")
    if not raw_path:
        raw_path = agent.diff_path
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    return os.path.expanduser(raw_path.strip())


def _persisted_commit_lines(
    agent: Agent,
    step_output: dict[str, Any] | None,
) -> tuple[_CommitLine, ...]:
    if step_output is None:
        return ()

    message = _display_text(step_output.get("meta_commit_message", ""))
    sha = _full_sha(step_output.get("meta_new_commit", ""))
    short_sha = _short_sha(sha)
    subject = _first_subject_line(message)
    if not subject and not short_sha:
        return ()
    if not subject:
        subject = "(message unavailable)"
    cwd_raw = step_output.get("meta_commit_cwd")
    attribution = _repo_attribution_for_commit_cwd(agent, step_output, cwd_raw)
    repo_name = attribution.name
    cwd = _display_text(cwd_raw) if cwd_raw is not None else None
    if cwd == "":
        cwd = None
    created_at = _parse_created_at(step_output.get("meta_commit_committed_at"))
    from ._agent_display_state import CommitViewSpec

    return (
        _CommitLine(
            short_sha=short_sha,
            subject=subject,
            view_spec=CommitViewSpec(
                short_sha=short_sha,
                sha=sha,
                repo_name=repo_name,
                cwd=cwd,
                subject=subject,
                message=message or subject,
                diff_path=_legacy_commit_diff_path(agent, step_output),
                is_primary=attribution.kind == "primary",
                repo_kind=attribution.kind,
                plan_workspaces=_agent_plan_workspaces(agent),
                created_at=created_at,
            ),
        ),
    )


def _parse_created_at(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return None
        return parsed if parsed >= 0 else None
    return None


def _commit_created_at_from_record(record: dict[str, Any]) -> int | None:
    return _parse_created_at(record.get("committed_at"))


def _commit_info_from_record(record: dict[str, Any]) -> _CommitInfo | None:
    message = _display_text(record.get("message", ""))
    sha = _short_sha(_full_sha(record.get("sha", record.get("result", ""))))
    subject = _first_subject_line(message)
    if not subject and not sha:
        return None
    if not subject:
        subject = "(message unavailable)"
    return _CommitInfo(short_sha=sha, subject=subject)


def _commit_line_from_record(
    agent: Agent,
    step_output: dict[str, Any] | None,
    record: dict[str, Any],
) -> _CommitLine | None:
    message = _display_text(record.get("message", ""))
    sha = _full_sha(record.get("sha", record.get("result", "")))
    short_sha = _short_sha(sha)
    subject = _first_subject_line(message)
    if not subject and not short_sha:
        return None
    if not subject:
        subject = "(message unavailable)"
    cwd_raw = record.get("cwd")
    attribution = _repo_attribution_for_commit_record(agent, step_output, record)
    repo_name = attribution.name
    cwd = _display_text(cwd_raw) if cwd_raw is not None else None
    if cwd == "":
        cwd = None
    from ._agent_display_state import CommitViewSpec

    return _CommitLine(
        short_sha=short_sha,
        subject=subject,
        view_spec=CommitViewSpec(
            short_sha=short_sha,
            sha=sha,
            repo_name=repo_name,
            cwd=cwd,
            subject=subject,
            message=message or subject,
            diff_path=_commit_diff_path_from_record(record),
            is_primary=attribution.kind == "primary",
            repo_kind=attribution.kind,
            plan_workspaces=_agent_plan_workspaces(agent),
            created_at=_commit_created_at_from_record(record),
        ),
    )


def _commit_diff_path_from_record(record: dict[str, Any]) -> str | None:
    raw_path = record.get("diff_path") or record.get("commit_diff_path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    return os.path.expanduser(raw_path.strip())


def _norm_path(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return os.path.normcase(
        os.path.normpath(os.path.abspath(os.path.expanduser(value)))
    )


def _path_is_same_or_inside(child: str | None, parent: str | None) -> bool:
    if child is None or parent is None:
        return False
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:
        return False


def _repo_name_from_cwd(cwd: str) -> str:
    basename = os.path.basename(os.path.normpath(os.path.expanduser(cwd)))
    repo_name = re.sub(r"_\d+$", "", basename).strip()
    return project_display_name_for(repo_name) if repo_name else "repository"


def _external_repo_attribution_for_cwd(
    agent: Agent,
    cwd: str | None,
) -> _RepoAttribution | None:
    workspace = _norm_path(agent.workspace_dir)
    if workspace is None:
        return None
    external_root = _norm_path(os.path.join(workspace, *EXTERNAL_REPO_CLONES_SUBDIR))
    if not _path_is_same_or_inside(cwd, external_root):
        return None
    assert cwd is not None and external_root is not None
    relative = os.path.relpath(cwd, external_root)
    parts = tuple(part for part in relative.split(os.sep) if part not in {"", "."})
    clone_part_count = 2 if parts and parts[0] == "projects" else 3
    if len(parts) < clone_part_count:
        return None
    clone_parts = parts[:clone_part_count]
    repo_name = external_repo_name_from_clone_parts(clone_parts)
    if repo_name is None:
        return None
    return _RepoAttribution(
        repo_name,
        "external",
        os.path.join(external_root, *clone_parts),
    )


def _sidecar_repo_attribution_for_cwd(
    agent: Agent,
    cwd: str | None,
) -> _RepoAttribution | None:
    workspace = _norm_path(agent.workspace_dir)
    if workspace is None:
        return None
    sidecars_root = _norm_path(os.path.join(workspace, "sase", "repos"))
    if _path_is_same_or_inside(cwd, sidecars_root):
        assert cwd is not None and sidecars_root is not None
        relative = os.path.relpath(cwd, sidecars_root)
        parts = tuple(part for part in relative.split(os.sep) if part not in {"", "."})
        if parts and parts[0] not in {"external", "linked"}:
            sidecar = os.path.join(sidecars_root, parts[0])
            return _RepoAttribution(parts[0], "sidecar", sidecar)
    legacy = _norm_path(os.path.join(workspace, ".sase", "sdd"))
    if _path_is_same_or_inside(cwd, legacy):
        assert legacy is not None
        return _RepoAttribution("sdd", "sidecar", legacy)
    return None


def _repo_attribution_for_commit_cwd(
    agent: Agent,
    step_output: dict[str, Any] | None,
    cwd_raw: object,
) -> _RepoAttribution:
    cwd = _norm_path(cwd_raw)
    primary_name = _primary_repo_name(agent, step_output)
    primary_workspace = _norm_path(agent.workspace_dir) or ""
    if cwd is None:
        return _RepoAttribution(primary_name, "primary", primary_workspace)

    external = _external_repo_attribution_for_cwd(agent, cwd)
    if external is not None:
        return external

    # Linked workspaces may also live below the primary workspace tree, so
    # match them before the containing primary workspace.
    for repo in agent.linked_repos:
        repo_workspace = _norm_path(repo.workspace_dir)
        if _path_is_same_or_inside(cwd, repo_workspace):
            return _RepoAttribution(repo.name, "linked", repo_workspace or "")

    sidecar = _sidecar_repo_attribution_for_cwd(agent, cwd)
    if sidecar is not None:
        return sidecar

    if _path_is_same_or_inside(cwd, _norm_path(agent.workspace_dir)):
        return _RepoAttribution(primary_name, "primary", primary_workspace)

    return _RepoAttribution(_repo_name_from_cwd(str(cwd_raw)), "linked", cwd)


def _repo_name_for_commit_cwd(
    agent: Agent,
    step_output: dict[str, Any] | None,
    cwd_raw: object,
) -> str:
    return _repo_attribution_for_commit_cwd(agent, step_output, cwd_raw).name


def _repo_attribution_for_commit_record(
    agent: Agent,
    step_output: dict[str, Any] | None,
    record: dict[str, Any],
) -> _RepoAttribution:
    attribution = _repo_attribution_for_commit_cwd(
        agent,
        step_output,
        record.get("cwd"),
    )
    explicit_name = _explicit_repo_name_from_record(record)
    explicit_kind = _explicit_repo_kind_from_record(record)
    legacy_sidecar_placeholder = (
        explicit_name == "sdd"
        and attribution.kind == "sidecar"
        and attribution.name != "sdd"
    )
    repo_name = (
        attribution.name
        if legacy_sidecar_placeholder
        else explicit_name or attribution.name
    )
    repo_kind = explicit_kind or attribution.kind
    workspace_dir = attribution.workspace_dir
    if (
        explicit_name is not None
        and explicit_kind is None
        and attribution.kind == "primary"
        and explicit_name != _primary_repo_name(agent, step_output)
    ):
        # Legacy records could carry only repo_name. An explicit non-primary
        # name must not become primary merely because cwd metadata is absent.
        repo_kind = "linked"
        workspace_dir = ""
    return _RepoAttribution(repo_name, repo_kind, workspace_dir)


def _explicit_repo_name_from_record(record: dict[str, Any]) -> str | None:
    repo_name = record.get("repo_name")
    return (
        repo_name.strip() if isinstance(repo_name, str) and repo_name.strip() else None
    )


def _explicit_repo_kind_from_record(record: dict[str, Any]) -> RepoKind | None:
    repo_kind = record.get("repo_kind")
    if repo_kind in {"primary", "sidecar", "linked", "external"}:
        return repo_kind  # type: ignore[return-value]
    return None


def _persisted_commit_repo_name(
    agent: Agent,
    step_output: dict[str, Any] | None,
) -> str:
    cwd_raw = step_output.get("meta_commit_cwd") if step_output is not None else None
    return _repo_name_for_commit_cwd(agent, step_output, cwd_raw)


def _persisted_commit_groups(
    agent: Agent,
    step_output: dict[str, Any] | None,
) -> tuple[_AgentCommitGroup, ...]:
    if step_output is None:
        return ()

    raw_commits = step_output.get("meta_commits")
    if isinstance(raw_commits, list) and raw_commits:
        grouped: dict[tuple[str, RepoKind], list[_CommitLine]] = {}
        group_order: list[tuple[str, RepoKind]] = []
        for raw_record in raw_commits:
            if not isinstance(raw_record, dict):
                continue
            commit = _commit_line_from_record(agent, step_output, raw_record)
            if commit is None:
                continue
            key = (commit.view_spec.repo_name, commit.view_spec.repo_kind)
            if key not in grouped:
                grouped[key] = []
                group_order.append(key)
            grouped[key].append(commit)

        if grouped:
            primary_name = _primary_repo_name(agent, step_output)
            ordered_groups: list[_AgentCommitGroup] = []
            primary_key: tuple[str, RepoKind] = (primary_name, "primary")
            if primary_key in grouped:
                ordered_groups.append(
                    _AgentCommitGroup(
                        primary_name,
                        "primary",
                        tuple(grouped[primary_key]),
                    )
                )
            for repo_name, repo_kind in sorted(
                group_order,
                key=lambda key: key[1] == "external",
            ):
                if (repo_name, repo_kind) == primary_key:
                    continue
                ordered_groups.append(
                    _AgentCommitGroup(
                        repo_name,
                        repo_kind,
                        tuple(grouped[(repo_name, repo_kind)]),
                    )
                )
            return tuple(ordered_groups)

    persisted_commits = _persisted_commit_lines(agent, step_output)
    if not persisted_commits:
        return ()
    commit = persisted_commits[0]
    return (
        _AgentCommitGroup(
            _persisted_commit_repo_name(agent, step_output),
            commit.view_spec.repo_kind,
            persisted_commits,
        ),
    )


def agent_commit_groups(agent: Agent) -> tuple[_AgentCommitGroup, ...]:
    """Return ordered in-memory commit rows grouped by source repository."""
    step_output = agent.step_output if isinstance(agent.step_output, dict) else None
    return _persisted_commit_groups(agent, step_output)


def agent_commit_view_specs(
    agent: Agent,
) -> tuple[tuple[CommitViewSpec, str, RepoKind], ...]:
    """Return ordered public commit-view records parsed without disk I/O."""
    return tuple(
        (commit.view_spec, group.repo_name, group.repo_kind)
        for group in agent_commit_groups(agent)
        for commit in group.commits
    )


def count_agent_commit_groups(commit_groups: tuple[_AgentCommitGroup, ...]) -> int:
    """Return the number of commit rows across attributed repository groups."""
    return sum(len(group.commits) for group in commit_groups)


def agent_commit_diffs(agent: Agent) -> list[CommitDiffInfo]:
    """Return ordered persisted per-commit diff descriptors for ``agent``.

    This accessor only parses in-memory metadata. It deliberately avoids
    checking file existence so render paths can call it without disk I/O.
    """
    step_output = agent.step_output if isinstance(agent.step_output, dict) else None
    if step_output is None:
        return []

    raw_commits = step_output.get("meta_commits")
    if not isinstance(raw_commits, list) or not raw_commits:
        return []

    primary_name = _primary_repo_name(agent, step_output)
    grouped: dict[tuple[str, RepoKind], list[CommitDiffInfo]] = {}
    group_order: list[tuple[str, RepoKind]] = []
    seen_paths: set[str] = set()
    for raw_record in raw_commits:
        if not isinstance(raw_record, dict):
            continue

        diff_path = _commit_diff_path_from_record(raw_record)
        path_key = _norm_path(diff_path)
        if diff_path is None or path_key is None or path_key in seen_paths:
            continue

        commit = _commit_info_from_record(raw_record)
        if commit is None:
            continue
        seen_paths.add(path_key)

        attribution = _repo_attribution_for_commit_record(
            agent,
            step_output,
            raw_record,
        )
        repo_name = attribution.name
        key = (repo_name, attribution.kind)
        if key not in grouped:
            grouped[key] = []
            group_order.append(key)
        grouped[key].append(
            CommitDiffInfo(
                repo_name=repo_name,
                short_sha=commit.short_sha,
                subject=commit.subject,
                diff_path=diff_path,
                is_primary=attribution.kind == "primary",
                repo_kind=attribution.kind,
                workspace_dir=attribution.workspace_dir,
            )
        )

    ordered: list[CommitDiffInfo] = []
    primary_key: tuple[str, RepoKind] = (primary_name, "primary")
    if primary_key in grouped:
        ordered.extend(grouped[primary_key])
    for key in sorted(group_order, key=lambda value: value[1] == "external"):
        if key == primary_key:
            continue
        ordered.extend(grouped[key])
    return ordered


def _append_commit_group(
    text: Text,
    repo_name: str,
    repo_kind: RepoKind,
    commits: tuple[_CommitLine, ...],
    hint_state: HeaderHintState | None = None,
    *,
    indent: str = "",
) -> None:
    if not commits:
        return

    text.append(f"{indent}  ")
    external = repo_kind == "external"
    text.append(
        EXTERNAL_REPO_GLYPH if external else WORKSPACE_GLYPH,
        style=COLOR_EXTERNAL_REPO_GLYPH if external else COLOR_WORKSPACE_GLYPH,
    )
    text.append(" ")
    text.append(
        repo_name,
        style=COLOR_EXTERNAL_REPO_NAME if external else COLOR_WORKSPACE_NAME,
    )
    text.append("\n")
    for commit in commits:
        text.append(f"{indent}    ")
        if hint_state is not None:
            hint_number = hint_state.hint_counter
            text.append(f"[{hint_number}] ", style="bold #FFFF00")
            hint_state.commit_views[hint_number] = commit.view_spec
            hint_state.hint_counter += 1
        if commit.short_sha:
            text.append(commit.short_sha, style=_COLOR_COMMIT_SHA)
            text.append(" ")
        text.append(commit.subject, style=_COLOR_COMMIT_SUBJECT)
        text.append("\n")


def append_agent_commit_groups(
    text: Text,
    commit_groups: tuple[_AgentCommitGroup, ...],
    hint_state: HeaderHintState | None = None,
    *,
    indent: str = "",
) -> None:
    """Append commit rows attributed to their source repositories."""
    for group in commit_groups:
        _append_commit_group(
            text,
            group.repo_name,
            group.repo_kind,
            group.commits,
            hint_state=hint_state,
            indent=indent,
        )


def _read_commit_diff_text(diff_path: str) -> str | None:
    try:
        with open(os.path.expanduser(diff_path), encoding="utf-8") as f:
            diff_text = f.read()
    except (OSError, UnicodeDecodeError):
        return None
    return diff_text if diff_text.strip() else None


def load_commit_diff_text(spec: CommitViewSpec) -> str | None:
    """Load a commit diff from the persisted file or VCS fallback."""
    if spec.diff_path:
        diff_text = _read_commit_diff_text(spec.diff_path)
        if diff_text:
            return diff_text

    if not spec.sha or not spec.cwd:
        return None

    try:
        from sase.vcs_provider import get_vcs_provider

        provider = get_vcs_provider(spec.cwd)
        ok, diff_text = provider.show_revision(spec.sha, spec.cwd)
    except Exception:
        return None
    if not ok or not diff_text or not diff_text.strip():
        return None
    return diff_text


def load_commit_created_at(spec: CommitViewSpec) -> int | None:
    """Resolve a commit's author time from the VCS when it was never recorded."""
    if spec.created_at is not None or not spec.sha or not spec.cwd:
        return None

    try:
        from sase.vcs_provider import get_vcs_provider

        provider = get_vcs_provider(spec.cwd)
        commits = provider.log(spec.cwd, 1, revs=(spec.sha,))
    except Exception:
        return None

    if not commits:
        return None
    commit = commits[0]
    target = spec.sha.lower()
    if commit.full_id.lower() != target and commit.short_id.lower() != target:
        return None
    return commit.timestamp
