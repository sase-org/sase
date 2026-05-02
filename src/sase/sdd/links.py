"""Validation and repair helpers for linked SDD prompt and plan files."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]

from sase.sdd.frontmatter import set_frontmatter_fields

PLAN_KINDS = ("tales", "epics", "legends")
LEGACY_PLAN_KINDS = ("plans",)
PROMPT_KINDS = ("prompts", "specs")
LIST_KINDS = ("prompts", "tales", "epics", "legends")
Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class _SddIssue:
    severity: Severity
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class _SddFile:
    path: Path
    relpath: str
    kind: str
    yyyymm: str
    name: str
    frontmatter: dict[str, Any]
    had_frontmatter: bool
    parse_error: str | None = None


@dataclass(frozen=True)
class _SddValidation:
    root: Path
    files: list[_SddFile]
    issues: list[_SddIssue]

    @property
    def errors(self) -> list[_SddIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[_SddIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class _RepairAction:
    path: str
    field: str
    old: str | None
    new: str


@dataclass(frozen=True)
class _RepairReport:
    root: Path
    write: bool
    actions: list[_RepairAction]
    issues: list[_SddIssue]
    changed_files: list[str]


def resolve_sdd_root(path: str | None = None, *, cwd: Path | None = None) -> Path:
    """Resolve an SDD root from either an SDD dir or a project dir."""
    base = Path.cwd() if cwd is None else cwd
    if path is None:
        for candidate in (base / "sdd", base / ".sase" / "sdd"):
            if candidate.is_dir():
                return candidate.resolve()
        return (base / "sdd").resolve()

    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    if candidate.is_dir() and _looks_like_project_root(candidate):
        candidate = candidate / "sdd"
    return candidate.resolve()


def validate_sdd_tree(
    path: str | None = None, *, strict: bool = False
) -> _SddValidation:
    """Validate frontmatter and bidirectional links under an SDD root."""
    root = resolve_sdd_root(path)
    if not root.is_dir():
        issue = _SddIssue(
            severity="error",
            code="invalid-root",
            path=str(root),
            message=f"SDD path does not exist or is not a directory: {root}",
        )
        return _SddValidation(root=root, files=[], issues=[issue])

    files = list_sdd_files(root, kind="all")
    by_path = {file.path.resolve(): file for file in files}
    issues: list[_SddIssue] = []

    for file in files:
        if file.parse_error is not None:
            issues.append(
                _SddIssue(
                    severity="error",
                    code="frontmatter-parse",
                    path=file.relpath,
                    message=file.parse_error,
                )
            )
            continue

        link_field = "plan" if file.kind == "prompts" else "prompt"
        link_value = file.frontmatter.get(link_field)
        counterpart = _infer_counterpart(file, files)
        if len(counterpart) == 1 and link_field not in file.frontmatter:
            issues.append(
                _SddIssue(
                    severity="error",
                    code="missing-link",
                    path=file.relpath,
                    message=f"missing {link_field!r} link to {counterpart[0].relpath}",
                )
            )
        elif len(counterpart) > 1:
            issues.append(
                _SddIssue(
                    severity=_strict_severity(strict),
                    code="ambiguous-counterpart",
                    path=file.relpath,
                    message="multiple inferable counterpart files: "
                    + ", ".join(item.relpath for item in counterpart),
                )
            )
        elif not counterpart and link_field not in file.frontmatter:
            issues.append(
                _SddIssue(
                    severity=_strict_severity(strict),
                    code="unpaired-file",
                    path=file.relpath,
                    message="no inferable counterpart file",
                )
            )

        if link_field not in file.frontmatter:
            continue
        if not isinstance(link_value, str):
            issues.append(
                _SddIssue(
                    severity="error",
                    code="link-type",
                    path=file.relpath,
                    message=f"{link_field!r} must be a string path",
                )
            )
            continue

        target_path = _resolve_link_path(root, link_value)
        target = by_path.get(target_path.resolve())
        if target is None:
            issues.append(
                _SddIssue(
                    severity="error",
                    code="link-missing-target",
                    path=file.relpath,
                    message=f"{link_field!r} target does not exist: {link_value}",
                )
            )
            continue

        if file.kind == "prompts" and target.kind not in PLAN_KINDS:
            issues.append(
                _SddIssue(
                    severity="error",
                    code="link-kind",
                    path=file.relpath,
                    message=f"{link_field!r} target is not a plan file: {target.relpath}",
                )
            )
        elif file.kind in PLAN_KINDS and target.kind != "prompts":
            issues.append(
                _SddIssue(
                    severity="error",
                    code="link-kind",
                    path=file.relpath,
                    message=f"{link_field!r} target is not a prompt file: {target.relpath}",
                )
            )

        reverse_field = "prompt" if file.kind == "prompts" else "plan"
        reverse_value = target.frontmatter.get(reverse_field)
        if not isinstance(reverse_value, str):
            issues.append(
                _SddIssue(
                    severity="error",
                    code="reverse-link",
                    path=file.relpath,
                    message=f"{target.relpath} is missing string {reverse_field!r} link",
                )
            )
            continue

        reverse_path = _resolve_link_path(root, reverse_value).resolve()
        if reverse_path != file.path.resolve():
            issues.append(
                _SddIssue(
                    severity="error",
                    code="reverse-link",
                    path=file.relpath,
                    message=f"{target.relpath} links back to {reverse_value}, not {file.relpath}",
                )
            )

    return _SddValidation(root=root, files=files, issues=issues)


def list_sdd_files(root: Path, *, kind: str = "all") -> list[_SddFile]:
    """Return known SDD markdown files under ``root``."""
    if kind == "plans":
        kind = "tales"
    kinds = LIST_KINDS if kind == "all" else (kind,)
    files: list[_SddFile] = []
    for item_kind in kinds:
        scan_kinds: tuple[str, ...]
        if item_kind == "prompts":
            scan_kinds = PROMPT_KINDS
        elif item_kind == "tales":
            scan_kinds = ("tales", *LEGACY_PLAN_KINDS)
        else:
            scan_kinds = (item_kind,)
        for physical_kind in scan_kinds:
            kind_root = root / physical_kind
            if not kind_root.is_dir():
                continue
            for path in sorted(kind_root.glob("*/*.md")):
                sdd_file = _read_sdd_file(root, path, item_kind)
                if sdd_file is not None:
                    files.append(sdd_file)
    return sorted(files, key=lambda file: file.relpath)


def collect_sdd_links(root: Path) -> list[dict[str, Any]]:
    """Return link rows suitable for text or JSON display."""
    files = list_sdd_files(root, kind="all")
    by_path = {file.path.resolve(): file for file in files}
    rows: list[dict[str, Any]] = []
    for file in files:
        link_field = "plan" if file.kind == "prompts" else "prompt"
        link_value = file.frontmatter.get(link_field)
        row: dict[str, Any] = {
            "path": file.relpath,
            "kind": file.kind,
            "field": link_field,
            "target": link_value if isinstance(link_value, str) else None,
            "target_exists": False,
            "bidirectional": False,
        }
        if isinstance(link_value, str):
            target = by_path.get(_resolve_link_path(root, link_value).resolve())
            row["target_exists"] = target is not None
            if target is not None:
                reverse_field = "prompt" if file.kind == "prompts" else "plan"
                reverse_value = target.frontmatter.get(reverse_field)
                row["bidirectional"] = (
                    isinstance(reverse_value, str)
                    and _resolve_link_path(root, reverse_value).resolve()
                    == file.path.resolve()
                )
        rows.append(row)
    return rows


def repair_sdd_links(path: str | None = None, *, write: bool = False) -> _RepairReport:
    """Infer unambiguous SDD pairs and repair missing or stale link fields."""
    root = resolve_sdd_root(path)
    if not root.is_dir():
        issue = _SddIssue(
            severity="error",
            code="invalid-root",
            path=str(root),
            message=f"SDD path does not exist or is not a directory: {root}",
        )
        return _RepairReport(
            root=root, write=write, actions=[], issues=[issue], changed_files=[]
        )

    files = list_sdd_files(root, kind="all")
    issues: list[_SddIssue] = []
    updates: dict[Path, dict[str, str]] = defaultdict(dict)
    actions: list[_RepairAction] = []

    for prompt_file in [file for file in files if file.kind == "prompts"]:
        if prompt_file.parse_error is not None:
            issues.append(
                _SddIssue(
                    severity="error",
                    code="frontmatter-parse",
                    path=prompt_file.relpath,
                    message=prompt_file.parse_error,
                )
            )
            continue
        candidates = _infer_counterpart(prompt_file, files)
        if len(candidates) != 1:
            if len(candidates) > 1:
                issues.append(
                    _SddIssue(
                        severity="warning",
                        code="ambiguous-counterpart",
                        path=prompt_file.relpath,
                        message="skipping ambiguous counterparts: "
                        + ", ".join(item.relpath for item in candidates),
                    )
                )
            continue
        plan_file = candidates[0]
        if plan_file.parse_error is not None:
            issues.append(
                _SddIssue(
                    severity="error",
                    code="frontmatter-parse",
                    path=plan_file.relpath,
                    message=plan_file.parse_error,
                )
            )
            continue
        _queue_update(root, prompt_file, "plan", plan_file, updates, actions)
        _queue_update(root, plan_file, "prompt", prompt_file, updates, actions)

    changed_files: list[str] = []
    if write:
        for file_path, fields in sorted(updates.items(), key=lambda item: str(item[0])):
            content = file_path.read_text(encoding="utf-8")
            file_path.write_text(
                set_frontmatter_fields(content, fields), encoding="utf-8"
            )
            changed_files.append(_relpath(root, file_path))

    return _RepairReport(
        root=root,
        write=write,
        actions=actions,
        issues=issues,
        changed_files=changed_files,
    )


def validation_to_json(validation: _SddValidation) -> dict[str, Any]:
    return {
        "root": str(validation.root),
        "ok": validation.ok,
        "files": [_file_to_json(file) for file in validation.files],
        "errors": [asdict(issue) for issue in validation.errors],
        "warnings": [asdict(issue) for issue in validation.warnings],
    }


def repair_to_json(report: _RepairReport) -> dict[str, Any]:
    return {
        "root": str(report.root),
        "write": report.write,
        "actions": [asdict(action) for action in report.actions],
        "warnings": [
            asdict(issue) for issue in report.issues if issue.severity == "warning"
        ],
        "errors": [
            asdict(issue) for issue in report.issues if issue.severity == "error"
        ],
        "changed_files": report.changed_files,
    }


def files_to_json(files: list[_SddFile]) -> list[dict[str, Any]]:
    return [_file_to_json(file) for file in files]


def _resolve_link_path(root: Path, link: str) -> Path:
    """Resolve a frontmatter link string to a filesystem path."""
    link_path = Path(link)
    if link_path.is_absolute():
        return link_path

    candidates = [
        root / link_path,
        root.parent / link_path,
        root.parent.parent / link_path,
        Path.cwd() / link_path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    for prefix in ("sdd/plans/", ".sase/sdd/plans/", "plans/"):
        if link.startswith(prefix):
            alias_path = Path(
                link.replace(prefix, prefix.replace("plans/", "tales/"), 1)
            )
            alias_candidates = [
                root / alias_path,
                root.parent / alias_path,
                root.parent.parent / alias_path,
                Path.cwd() / alias_path,
            ]
            for candidate in alias_candidates:
                if candidate.exists():
                    return candidate
    if link.startswith("sdd/") or link.startswith(".sase/sdd/"):
        return root.parent / link_path
    return root / link_path


def _link_value_for(root: Path, target: Path) -> str:
    relative = target.relative_to(root).as_posix()
    if root.name == "sdd" and root.parent.name == ".sase":
        return f".sase/sdd/{relative}"
    if root.name == "sdd":
        return f"sdd/{relative}"
    return relative


def _read_sdd_file(root: Path, path: Path, kind: str) -> _SddFile | None:
    parts = path.relative_to(root).parts
    if len(parts) != 3:
        return None
    yyyymm = parts[1]
    name = path.stem
    frontmatter, _, had_frontmatter, parse_error = _parse_frontmatter_strict(
        path.read_text(encoding="utf-8")
    )
    return _SddFile(
        path=path,
        relpath=_relpath(root, path),
        kind=kind,
        yyyymm=yyyymm,
        name=name,
        frontmatter=frontmatter,
        had_frontmatter=had_frontmatter,
        parse_error=parse_error,
    )


def _parse_frontmatter_strict(
    content: str,
) -> tuple[dict[str, Any], str, bool, str | None]:
    if not content.startswith("---\n"):
        return {}, content, False, None
    end = content.find("\n---\n", 4)
    if end == -1:
        return {}, content, True, "frontmatter closing marker not found"
    raw = content[4:end]
    try:
        parsed = yaml.safe_load(raw) if raw.strip() else {}
    except yaml.YAMLError as exc:
        return {}, content[end + 5 :], True, f"invalid YAML frontmatter: {exc}"
    if parsed is None:
        parsed = {}
    if not isinstance(parsed, dict):
        return {}, content[end + 5 :], True, "frontmatter must be a YAML mapping"
    return dict(parsed), content[end + 5 :], True, None


def _infer_counterpart(file: _SddFile, files: list[_SddFile]) -> list[_SddFile]:
    if file.kind == "prompts":
        wanted = set(PLAN_KINDS)
    else:
        wanted = {"prompts"}
    return [
        candidate
        for candidate in files
        if candidate.kind in wanted
        and candidate.yyyymm == file.yyyymm
        and candidate.name == file.name
    ]


def _queue_update(
    root: Path,
    source: _SddFile,
    field: str,
    target: _SddFile,
    updates: dict[Path, dict[str, str]],
    actions: list[_RepairAction],
) -> None:
    new = _link_value_for(root, target.path)
    old_value = source.frontmatter.get(field)
    old = old_value if isinstance(old_value, str) else None
    if old == new:
        return
    updates[source.path][field] = new
    actions.append(_RepairAction(path=source.relpath, field=field, old=old, new=new))


def _file_to_json(file: _SddFile) -> dict[str, Any]:
    return {
        "path": file.relpath,
        "kind": file.kind,
        "yyyymm": file.yyyymm,
        "name": file.name,
        "has_frontmatter": file.had_frontmatter,
        "parse_error": file.parse_error,
    }


def _relpath(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _strict_severity(strict: bool) -> Severity:
    return "error" if strict else "warning"


def _looks_like_project_root(path: Path) -> bool:
    return (path / "sdd").is_dir() and not any(
        (path / kind).is_dir() for kind in (*LIST_KINDS, *LEGACY_PLAN_KINDS)
    )
