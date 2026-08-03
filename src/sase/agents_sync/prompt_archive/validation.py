"""Read-only validation for the canonical agents-sidecar prompt archive."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Literal, cast
from urllib.parse import unquote, urlsplit

from sase.agents_sync.publication_outbox import (
    AGENT_PUBLICATION_OUTBOX_FILENAME,
    snapshot_agent_publications_from_path,
)
from sase.core.paths import sase_projects_dir
from sase.core.prompt_artifact_staging import (
    PROMPT_ARTIFACT_MANIFEST_NAME,
    PromptArtifactRecord,
)
from sase.core.rust import require_rust_binding
from sase.history.chat_prompt_sections import (
    RENDERED_SECTION_END,
    RENDERED_SECTION_START,
    XPROMPT_SECTION_END,
    XPROMPT_SECTION_START,
)
from sase.sdd._paths import has_month_dirs, is_month_dir_name
from sase.sdd.plan_header_block import (
    PlanHeaderDisposition,
    PlanHeaderSection,
    PlanHeaderSectionKind,
    parse_plan_header_block,
)

PromptArchiveSeverity = Literal["error", "warning"]

_ARTIFACT_FILENAME_RE = re.compile(r"^([0-9a-fA-F]{12})-")
_MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[([^\]\n]*)\]\(([^\s)]+)(?:\s+[^)]*)?\)")
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_RENDERED_FENCE_OPEN_RE = re.compile(r"^(`{3,})markdown\s*$")


@dataclass(frozen=True, slots=True)
class _PromptArchiveIssue:
    """One stable prompt-archive validation diagnostic."""

    severity: PromptArchiveSeverity
    code: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class _PromptArchiveFile:
    """One discovered canonical prompt document."""

    path: Path
    relpath: str
    month: str
    name: str
    title: str
    plan_label: str | None
    plan_target: str | None
    agent_labels: tuple[str, ...]
    artifact_count: int
    parse_error: str | None = None

    def to_json_dict(self) -> dict[str, object]:
        return {
            "path": self.relpath,
            "month": self.month,
            "name": self.name,
            "title": self.title,
            "plan_label": self.plan_label,
            "plan_target": self.plan_target,
            "agents": list(self.agent_labels),
            "artifact_count": self.artifact_count,
            "parse_error": self.parse_error,
        }


@dataclass(frozen=True, slots=True)
class PromptArchiveValidation:
    """Complete validation result for one agents-sidecar archive."""

    root: Path
    files: tuple[_PromptArchiveFile, ...]
    issues: tuple[_PromptArchiveIssue, ...]
    legacy_files: int = 0

    @property
    def errors(self) -> tuple[_PromptArchiveIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[_PromptArchiveIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_json_dict(self) -> dict[str, object]:
        return {
            "root": str(self.root),
            "ok": self.ok,
            "files": [file.to_json_dict() for file in self.files],
            "legacy_files": self.legacy_files,
            "errors": [asdict(issue) for issue in self.errors],
            "warnings": [asdict(issue) for issue in self.warnings],
        }


def validate_prompt_archive(
    repo: Path | str,
    *,
    month: str | None = None,
    plans_repo: Path | str | None = None,
    workspace_roots: tuple[Path, ...] = (),
    project_key: str | None = None,
) -> PromptArchiveValidation:
    """Validate prompt documents, published artifacts, and local manifests."""

    root = Path(repo).expanduser().resolve(strict=False)
    plans_root = _plans_root(plans_repo)
    files: list[_PromptArchiveFile] = []
    issues: list[_PromptArchiveIssue] = []
    referenced_artifacts: set[Path] = set()
    agents_by_month: dict[str, set[str]] = {}
    legacy_files = 0

    for path in _prompt_paths(root, month):
        prompt, sections, parse_error = _read_prompt(path)
        relpath = path.relative_to(root).as_posix()
        prompt_month = path.parent.name
        plan = _section(sections, PlanHeaderSectionKind.PLAN)
        agents = _section(sections, PlanHeaderSectionKind.AGENTS)
        artifacts = _section(sections, PlanHeaderSectionKind.ARTIFACTS)
        agent_labels = tuple(entry.label for entry in agents.entries) if agents else ()
        agents_by_month.setdefault(prompt_month, set()).update(agent_labels)
        files.append(
            _PromptArchiveFile(
                path=path,
                relpath=relpath,
                month=prompt_month,
                name=path.stem,
                title=_document_title(prompt, path.stem),
                plan_label=plan.label if plan is not None else None,
                plan_target=plan.target if plan is not None else None,
                agent_labels=agent_labels,
                artifact_count=len(artifacts.entries) if artifacts is not None else 0,
                parse_error=parse_error,
            )
        )
        if parse_error is not None:
            issues.append(
                _PromptArchiveIssue("error", "prompt-parse", relpath, parse_error)
            )
            continue

        has_rendered_section = _validate_prompt_sections(prompt, relpath, issues)
        if not has_rendered_section:
            legacy_files += 1
        _validate_xprompt_link_targets(prompt, relpath, issues)

        if plan is not None:
            _validate_plan_target(plan, relpath, plans_root, issues)

        targets = {
            entry.target
            for entry in (artifacts.entries if artifacts is not None else ())
            if entry.target
        }
        targets.update(_markdown_targets_outside_fences(prompt))
        missing_targets: set[str] = set()
        for target in sorted(targets):
            artifact_path = _local_artifact_path(root, path, target)
            if artifact_path is None:
                continue
            referenced_artifacts.add(artifact_path)
            if not artifact_path.is_file() and target not in missing_targets:
                missing_targets.add(target)
                issues.append(
                    _PromptArchiveIssue(
                        "error",
                        "artifact-missing",
                        relpath,
                        f"published artifact target does not exist: {target}",
                    )
                )

    for artifact in _artifact_paths(root, month):
        relpath = artifact.relative_to(root).as_posix()
        match = _ARTIFACT_FILENAME_RE.match(artifact.name)
        if (
            match is not None
            and _sha256(artifact)[:12].casefold() != match.group(1).casefold()
        ):
            issues.append(
                _PromptArchiveIssue(
                    "error",
                    "artifact-digest",
                    relpath,
                    "artifact bytes do not match the digest prefix in its filename",
                )
            )
        if artifact.resolve(strict=False) not in referenced_artifacts:
            issues.append(
                _PromptArchiveIssue(
                    "warning",
                    "artifact-orphan",
                    relpath,
                    "published artifact is referenced by no prompt",
                )
            )

    issues.extend(
        _unpublished_manifest_issues(
            workspace_roots,
            agents_by_month,
            month=month,
            project_key=project_key,
        )
    )
    return PromptArchiveValidation(
        root=root,
        files=tuple(files),
        issues=tuple(
            sorted(issues, key=lambda issue: (issue.path, issue.code, issue.message))
        ),
        legacy_files=legacy_files,
    )


def list_prompt_archive_files(
    repo: Path | str,
    *,
    month: str | None = None,
) -> tuple[_PromptArchiveFile, ...]:
    """Return prompt inventory without validating counterpart repositories."""

    return validate_prompt_archive(repo, month=month).files


def resolve_prompt_archive_file(
    repo: Path | str,
    reference: str,
) -> _PromptArchiveFile:
    """Resolve one prompt by canonical path, month/name, or unique stem."""

    normalized = reference.strip().removeprefix("prompts:").removeprefix("./")
    normalized = normalized.removeprefix("prompts/").removesuffix(".md")
    candidates = [
        file
        for file in list_prompt_archive_files(repo)
        if normalized
        in {
            file.name,
            f"{file.month}/{file.name}",
            file.relpath.removeprefix("prompts/").removesuffix(".md"),
        }
    ]
    if not candidates:
        raise ValueError(f"prompt archive entry not found: {reference}")
    if len(candidates) > 1:
        choices = ", ".join(file.relpath for file in candidates)
        raise ValueError(
            f"prompt archive reference is ambiguous: {reference} ({choices})"
        )
    return candidates[0]


def _prompt_paths(root: Path, month: str | None) -> tuple[Path, ...]:
    prompts_root = root / "prompts"
    pattern = f"{month}/*.md" if month is not None else "*/*.md"
    return tuple(
        path
        for path in sorted(prompts_root.glob(pattern))
        if path.name != "README.md" and path.parent.name != "README.md"
    )


def _artifact_paths(root: Path, month: str | None) -> tuple[Path, ...]:
    artifacts_root = root / "artifacts"
    pattern = f"{month}/*" if month is not None else "*/*"
    return tuple(
        path for path in sorted(artifacts_root.glob(pattern)) if path.is_file()
    )


def _read_prompt(
    path: Path,
) -> tuple[str, tuple[PlanHeaderSection, ...], str | None]:
    try:
        document = path.read_text(encoding="utf-8")
        parsed = parse_plan_header_block(document)
    except (OSError, UnicodeError, RuntimeError, ValueError) as exc:
        return "", (), str(exc) or type(exc).__name__
    if parsed.disposition is PlanHeaderDisposition.INVALID:
        return parsed.body, parsed.sections, parsed.reason or "invalid prompt header"
    return parsed.body, parsed.sections, None


def _section(
    sections: tuple[PlanHeaderSection, ...], kind: PlanHeaderSectionKind
) -> PlanHeaderSection | None:
    return next((section for section in sections if section.kind is kind), None)


def _validate_plan_target(
    plan: PlanHeaderSection,
    relpath: str,
    plans_root: Path | None,
    issues: list[_PromptArchiveIssue],
) -> None:
    if plans_root is None:
        issues.append(
            _PromptArchiveIssue(
                "warning",
                "plan-unresolved",
                relpath,
                "PLAN target cannot be checked because no local plans checkout is available",
            )
        )
        return
    label = (plan.label or "").removeprefix("plans:").removeprefix("plans/")
    relative = PurePosixPath(label)
    if (
        not label
        or relative.is_absolute()
        or ".." in relative.parts
        or not (plans_root / Path(*relative.parts)).is_file()
    ):
        issues.append(
            _PromptArchiveIssue(
                "warning",
                "plan-unresolved",
                relpath,
                f"PLAN target does not resolve in the local plans checkout: {plan.label or plan.target}",
            )
        )


def _plans_root(value: Path | str | None) -> Path | None:
    if value is None:
        return None
    root = Path(value).expanduser().resolve(strict=False)
    if not root.is_dir():
        return None
    nested = root / "plans"
    return nested if has_month_dirs(nested) else root


def _markdown_targets_outside_fences(document: str) -> set[str]:
    return {target for _label, target in _markdown_links_outside_fences(document)}


def _markdown_links_outside_fences(document: str) -> set[tuple[str, str]]:
    links: set[tuple[str, str]] = set()
    fence: str | None = None
    for line in document.splitlines():
        marker = _FENCE_RE.match(line)
        if marker is not None:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        if fence is None:
            links.update(
                (match.group(1), match.group(2))
                for match in _MARKDOWN_LINK_RE.finditer(line)
            )
    return links


def _validate_prompt_sections(
    document: str,
    relpath: str,
    issues: list[_PromptArchiveIssue],
) -> bool:
    rendered_payload: str | None = None
    rendered_present = False
    for label, start, end in (
        ("XPrompt", XPROMPT_SECTION_START, XPROMPT_SECTION_END),
        ("rendered prompt", RENDERED_SECTION_START, RENDERED_SECTION_END),
    ):
        start_count = document.count(start)
        end_count = document.count(end)
        if label == "rendered prompt":
            rendered_present = bool(start_count or end_count)
        if start_count == end_count == 0:
            continue
        start_at = document.find(start)
        end_at = document.find(end)
        if start_count != 1 or end_count != 1 or end_at < start_at:
            issues.append(
                _PromptArchiveIssue(
                    "error",
                    "prompt-section-sentinel",
                    relpath,
                    f"{label} section sentinels are not paired exactly once",
                )
            )
            continue
        if label == "rendered prompt":
            rendered_payload = document[start_at + len(start) : end_at]

    if rendered_payload is not None and not _rendered_fence_is_balanced(
        rendered_payload
    ):
        issues.append(
            _PromptArchiveIssue(
                "error",
                "rendered-prompt-fence",
                relpath,
                "rendered prompt section does not contain one balanced Markdown fence",
            )
        )
    return rendered_present


def _rendered_fence_is_balanced(section: str) -> bool:
    lines = section.splitlines()
    openings = [
        (index, match.group(1))
        for index, line in enumerate(lines)
        if (match := _RENDERED_FENCE_OPEN_RE.fullmatch(line.strip())) is not None
    ]
    if len(openings) != 1:
        return False
    opening_index, fence = openings[0]
    closings = [
        index
        for index, line in enumerate(lines)
        if index > opening_index and line.strip() == fence
    ]
    return len(closings) == 1


def _validate_xprompt_link_targets(
    document: str,
    relpath: str,
    issues: list[_PromptArchiveIssue],
) -> None:
    invalid = sorted(
        {
            target
            for label, target in _markdown_links_outside_fences(document)
            if label.startswith("#") and not _is_absolute_https_url(target)
        }
    )
    for target in invalid:
        issues.append(
            _PromptArchiveIssue(
                "error",
                "xprompt-link-target",
                relpath,
                f"xprompt link target must be an absolute https:// URL: {target}",
            )
        )


def _is_absolute_https_url(target: str) -> bool:
    parsed = urlsplit(target)
    return parsed.scheme.casefold() == "https" and bool(parsed.netloc)


def _local_artifact_path(root: Path, prompt: Path, target: str) -> Path | None:
    split = urlsplit(target)
    if split.scheme or split.netloc:
        return None
    raw_path = unquote(split.path)
    if not raw_path:
        return None
    candidate = (prompt.parent / raw_path).resolve(strict=False)
    artifacts_root = (root / "artifacts").resolve(strict=False)
    try:
        candidate.relative_to(artifacts_root)
    except ValueError:
        return None
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _unpublished_manifest_issues(
    workspace_roots: tuple[Path, ...],
    agents_by_month: dict[str, set[str]],
    *,
    month: str | None,
    project_key: str | None,
) -> list[_PromptArchiveIssue]:
    issues: list[_PromptArchiveIssue] = []
    seen_manifests: set[Path] = set()
    queued_agents = _queued_agent_hood_publications(project_key)
    for workspace in workspace_roots:
        manifest = (
            workspace.expanduser().resolve(strict=False)
            / ".sase"
            / "artifacts"
            / PROMPT_ARTIFACT_MANIFEST_NAME
        )
        if manifest in seen_manifests or not manifest.is_file():
            continue
        seen_manifests.add(manifest)
        try:
            parse = require_rust_binding("prompt_artifact_manifest_parse")
            records = cast(list[PromptArtifactRecord], parse(manifest.read_bytes()))
        except (OSError, RuntimeError, ValueError):
            continue
        run_dirs = sorted(
            {
                Path(record["agent_artifacts_dir"]).expanduser()
                for record in records
                if record.get("agent_artifacts_dir")
            }
        )
        for run_dir in run_dirs:
            run_month = _month_from_path(run_dir)
            if run_month is None or (month is not None and run_month != month):
                continue
            agent_name = _published_agent_name(run_dir)
            if agent_name is not None and agent_name in agents_by_month.get(
                run_month, set()
            ):
                continue
            try:
                display = manifest.relative_to(workspace).as_posix()
            except ValueError:
                display = str(manifest)
            message = (
                f"manifest run publication is queued: {run_dir}"
                if agent_name is not None and agent_name in queued_agents
                else f"manifest run has no matching published prompt: {run_dir}"
            )
            issues.append(
                _PromptArchiveIssue("warning", "prompt-unpublished", display, message)
            )
    return issues


def _queued_agent_hood_publications(project_key: str | None) -> frozenset[str]:
    """Return global agent names with a still-pending ``agent_hood`` request."""

    if not project_key:
        return frozenset()
    path = sase_projects_dir() / project_key / AGENT_PUBLICATION_OUTBOX_FILENAME
    try:
        items = snapshot_agent_publications_from_path(path, project_key)
    except Exception:
        return frozenset()
    return frozenset(
        item.global_agent
        for item in items
        if item.kind == "agent_hood" and not item.terminal
    )


def _published_agent_name(run_dir: Path) -> str | None:
    try:
        payload = json.loads((run_dir / "agent_meta.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    raw_name = payload.get("name") if isinstance(payload, dict) else None
    if not isinstance(raw_name, str) or not raw_name.strip():
        return None
    try:
        from sase.core.agent_identity_facade import (
            AgentIdentitySnapshot,
            globalize_owned_agent_name,
            normalize_owned_agent_name,
        )

        identity = AgentIdentitySnapshot.current()
        return globalize_owned_agent_name(
            normalize_owned_agent_name(raw_name, identity), identity
        )
    except Exception:
        return raw_name


def _month_from_path(path: Path) -> str | None:
    for part in reversed(path.parts):
        if len(part) >= 6 and is_month_dir_name(part[:6]):
            return part[:6]
    return None


def _document_title(document: str, fallback: str) -> str:
    for line in document.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped
    return fallback


__all__ = [
    "PromptArchiveValidation",
    "list_prompt_archive_files",
    "resolve_prompt_archive_file",
    "validate_prompt_archive",
]
