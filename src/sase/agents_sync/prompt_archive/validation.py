"""Read-only validation for the canonical agents-sidecar prompt archive."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Literal, cast
from urllib.parse import unquote, urlsplit

from sase.core.prompt_archive_facade import (
    PromptArchiveDocument,
    prompt_archive_inventory,
)
from sase.core.prompt_artifact_staging import (
    PROMPT_ARTIFACT_MANIFEST_NAME,
    PromptArtifactRecord,
)
from sase.core.rust import require_rust_binding
from sase.sdd._paths import has_month_dirs, is_month_dir_name
from sase.sdd.plan_header_block import (
    PlanHeaderSection,
    PlanHeaderSectionKind,
)
from sase.sdd.plan_refs import PLAN_REFERENCE_PREFIX

PromptArchiveSeverity = Literal["error", "warning"]

_ARTIFACT_FILENAME_RE = re.compile(r"^([0-9a-fA-F]{12})-")
_MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]\n]*\]\(([^\s)]+)(?:\s+[^)]*)?\)")
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")


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
            "errors": [asdict(issue) for issue in self.errors],
            "warnings": [asdict(issue) for issue in self.warnings],
        }


def validate_prompt_archive(
    repo: Path | str,
    *,
    month: str | None = None,
    plans_repo: Path | str | None = None,
    workspace_roots: tuple[Path, ...] = (),
) -> PromptArchiveValidation:
    """Validate prompt documents, published artifacts, and local manifests."""

    root = Path(repo).expanduser().resolve(strict=False)
    plans_root = _plans_root(plans_repo)
    files: list[_PromptArchiveFile] = []
    issues: list[_PromptArchiveIssue] = []
    referenced_artifacts: set[Path] = set()
    agents_by_month: dict[str, set[str]] = {}

    for document in prompt_archive_inventory(root, month=month):
        prompt = document.body
        sections = document.sections
        parse_error = document.parse_error
        relpath = document.relpath
        prompt_month = document.month
        path = document.path
        plan = _section(sections, PlanHeaderSectionKind.PLAN)
        agents = _section(sections, PlanHeaderSectionKind.AGENTS)
        artifacts = _section(sections, PlanHeaderSectionKind.ARTIFACTS)
        agent_labels = tuple(entry.label for entry in agents.entries) if agents else ()
        agents_by_month.setdefault(prompt_month, set()).update(agent_labels)
        files.append(
            _archive_file_from_document(
                document,
                plan=plan,
                agents=agents,
                artifacts=artifacts,
            )
        )
        if parse_error is not None:
            issues.append(
                _PromptArchiveIssue("error", "prompt-parse", relpath, parse_error)
            )
            continue

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
        )
    )
    return PromptArchiveValidation(
        root=root,
        files=tuple(files),
        issues=tuple(
            sorted(issues, key=lambda issue: (issue.path, issue.code, issue.message))
        ),
    )


def list_prompt_archive_files(
    repo: Path | str,
    *,
    month: str | None = None,
) -> tuple[_PromptArchiveFile, ...]:
    """Return prompt inventory without validating counterpart repositories."""

    return tuple(
        _archive_file_from_document(document)
        for document in prompt_archive_inventory(repo, month=month)
    )


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


def _archive_file_from_document(
    document: PromptArchiveDocument,
    *,
    plan: PlanHeaderSection | None = None,
    agents: PlanHeaderSection | None = None,
    artifacts: PlanHeaderSection | None = None,
) -> _PromptArchiveFile:
    if plan is None:
        plan = _section(document.sections, PlanHeaderSectionKind.PLAN)
    if agents is None:
        agents = _section(document.sections, PlanHeaderSectionKind.AGENTS)
    if artifacts is None:
        artifacts = _section(document.sections, PlanHeaderSectionKind.ARTIFACTS)
    agent_labels = tuple(entry.label for entry in agents.entries) if agents else ()
    return _PromptArchiveFile(
        path=document.path,
        relpath=document.relpath,
        month=document.month,
        name=document.name,
        title=_document_title(document.body, document.name),
        plan_label=plan.label if plan is not None else None,
        plan_target=plan.target if plan is not None else None,
        agent_labels=agent_labels,
        artifact_count=len(artifacts.entries) if artifacts is not None else 0,
        parse_error=document.parse_error,
    )


def _artifact_paths(root: Path, month: str | None) -> tuple[Path, ...]:
    artifacts_root = root / "artifacts"
    pattern = f"{month}/*" if month is not None else "*/*"
    return tuple(
        path for path in sorted(artifacts_root.glob(pattern)) if path.is_file()
    )


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
    # "plans:" is immutable-history: an archived prompt's PLAN section may
    # still carry the legacy spelling. Accept it here too. "plans/" is the
    # directory marker, not the reference prefix.
    label = (
        (plan.label or "")
        .removeprefix(PLAN_REFERENCE_PREFIX)
        .removeprefix("plans:")
        .removeprefix("plans/")
    )
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
    targets: set[str] = set()
    fence: str | None = None
    for line in document.splitlines():
        marker = _FENCE_RE.match(line)
        if marker is not None:
            token = marker.group(1)
            if fence is None:
                fence = token[0]
            elif token[0] == fence:
                fence = None
            continue
        if fence is None:
            targets.update(match.group(1) for match in _MARKDOWN_LINK_RE.finditer(line))
    return targets


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
) -> list[_PromptArchiveIssue]:
    issues: list[_PromptArchiveIssue] = []
    seen_manifests: set[Path] = set()
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
            issues.append(
                _PromptArchiveIssue(
                    "warning",
                    "prompt-unpublished",
                    display,
                    f"manifest run has no matching published prompt: {run_dir}",
                )
            )
    return issues


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
