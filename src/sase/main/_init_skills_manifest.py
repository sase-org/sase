"""Provenance and managed-file ownership for skill deployments."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import PurePosixPath
from pathlib import Path
import subprocess
from typing import Literal, Protocol

from sase.version._git import run_git
from sase.xprompt.loader import get_sase_package_skills_dir
from sase.xprompt.models import XPrompt

SKILLS_MANIFEST_FILENAME = ".sase-skills-manifest.json"
ManagedSkillState = Literal["active", "retired"]

_FORCE_INSTRUCTION = (
    "Use --force only as a deliberate escape hatch; it can revert other agents' "
    "skill deployments."
)
_GIT_ERRORS = (
    FileNotFoundError,
    OSError,
    subprocess.CalledProcessError,
    subprocess.TimeoutExpired,
)


class _RenderedSkillDeploymentTargetLike(Protocol):
    @property
    def source_path(self) -> Path: ...

    @property
    def home_path(self) -> Path: ...

    @property
    def provider(self) -> str: ...

    @property
    def skill_name(self) -> str: ...


@dataclass(frozen=True)
class ManagedSkillFile:
    """One generated skill file owned by SASE in source and live homes."""

    provider: str
    skill_name: str
    source_relpath: str
    home_relpath: str
    state: ManagedSkillState = "active"

    @property
    def path_key(self) -> tuple[str, str]:
        return (self.source_relpath, self.home_relpath)

    @property
    def sort_key(self) -> tuple[str, str, str, str]:
        return (
            self.provider,
            self.skill_name,
            self.source_relpath,
            self.home_relpath,
        )

    def with_state(self, state: ManagedSkillState) -> ManagedSkillFile:
        return ManagedSkillFile(
            provider=self.provider,
            skill_name=self.skill_name,
            source_relpath=self.source_relpath,
            home_relpath=self.home_relpath,
            state=state,
        )

    def source_path(self, chezmoi_home: Path) -> Path:
        return _safe_join(chezmoi_home, self.source_relpath)

    def home_path(self, home_root: Path) -> Path:
        return _safe_join(home_root, self.home_relpath)

    def to_json_dict(self) -> dict[str, str]:
        return {
            "home_path": self.home_relpath,
            "provider": self.provider,
            "skill_name": self.skill_name,
            "source_path": self.source_relpath,
            "state": self.state,
        }


@dataclass(frozen=True)
class SkillManifestOwnershipPlan:
    """Managed-file state reconciled against the current rendered target set."""

    entries: tuple[ManagedSkillFile, ...]
    retired_entries: tuple[ManagedSkillFile, ...]
    recorded: _SkillDeployManifest | None


@dataclass(frozen=True)
class _SkillDeployManifest:
    """Provenance for the generated skill set in the chezmoi repository."""

    source_commit: str
    xprompt_set_sha256: str
    deployed_at: str
    managed_files: tuple[ManagedSkillFile, ...] = ()

    def to_json(self) -> str:
        """Return the stable, version-controlled JSON representation."""
        return (
            json.dumps(
                {
                    "deployed_at": self.deployed_at,
                    "managed_files": [
                        entry.to_json_dict() for entry in self.managed_files
                    ],
                    "source_commit": self.source_commit,
                    "xprompt_set_sha256": self.xprompt_set_sha256,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )


@dataclass(frozen=True)
class _SkillManifestWrite:
    """A manifest write prepared before any deployment target is changed."""

    path: Path
    content: str | None
    source_commit: str
    retired_entries: tuple[ManagedSkillFile, ...] = ()


def _skill_xprompt_set_sha256(skill_xprompts: Sequence[XPrompt]) -> str:
    """Hash the selected fields that determine generated skill content.

    ``name`` is the provider skill name, not the ``skills/`` xprompt
    reference, so the recorded hash tracks what was actually deployed.
    """
    entries = [
        {
            "content": xprompt.content,
            "description": xprompt.description or "",
            "log_skill_use": xprompt.log_skill_use,
            "name": xprompt.skill_name or xprompt.name,
            "skill": xprompt.skill,
        }
        for xprompt in sorted(
            skill_xprompts, key=lambda item: item.skill_name or item.name
        )
    ]
    encoded = json.dumps(
        entries,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def prepare_skill_manifest(
    skill_xprompts: Sequence[XPrompt],
    *,
    chezmoi_home: Path,
    force: bool,
    current_targets: Sequence[_RenderedSkillDeploymentTargetLike] = (),
    provider_filter: str | None = None,
    registered_providers: Sequence[str] = (),
    home_root: Path | None = None,
) -> tuple[_SkillManifestWrite | None, str | None]:
    """Prepare a manifest write or return a pre-write refusal message."""
    manifest_path = chezmoi_home / SKILLS_MANIFEST_FILENAME
    if home_root is None:
        home_root = Path.home()
    ownership_plan, ownership_error = plan_skill_manifest_ownership(
        current_targets,
        chezmoi_home=chezmoi_home,
        home_root=home_root,
        provider_filter=provider_filter,
        registered_providers=registered_providers,
    )
    if ownership_error is not None:
        return None, ownership_error
    assert ownership_plan is not None

    try:
        source_root = Path(
            run_git(
                get_sase_package_skills_dir().resolve(),
                "rev-parse",
                "--show-toplevel",
            )
        ).resolve()
        incoming_commit = run_git(source_root, "rev-parse", "HEAD")
    except _GIT_ERRORS as exc:
        return None, (
            "refusing chezmoi skill deploy because source provenance could not "
            f"be resolved: {_git_error_detail(exc)}"
        )

    incoming_hash = _skill_xprompt_set_sha256(skill_xprompts)
    recorded = ownership_plan.recorded
    if recorded is None and not ownership_plan.entries and not skill_xprompts:
        return (
            _SkillManifestWrite(
                path=manifest_path,
                content=None,
                source_commit=incoming_commit,
            ),
            None,
        )
    if recorded is not None and recorded.source_commit != incoming_commit and not force:
        relation = _commit_relation(
            source_root,
            recorded=recorded.source_commit,
            incoming=incoming_commit,
        )
        if relation == "backwards":
            return None, _refusal_message(
                source_root,
                recorded=recorded.source_commit,
                incoming=incoming_commit,
                reason="the recorded source is newer; this would move the destination backwards",
            )
        if relation == "divergent":
            return None, _refusal_message(
                source_root,
                recorded=recorded.source_commit,
                incoming=incoming_commit,
                reason="the recorded and incoming sources are unrelated",
            )

    if (
        recorded is not None
        and recorded.source_commit == incoming_commit
        and recorded.xprompt_set_sha256 == incoming_hash
        and recorded.managed_files == ownership_plan.entries
    ):
        return (
            _SkillManifestWrite(
                path=manifest_path,
                content=None,
                source_commit=incoming_commit,
                retired_entries=ownership_plan.retired_entries,
            ),
            None,
        )

    manifest = _SkillDeployManifest(
        source_commit=incoming_commit,
        xprompt_set_sha256=incoming_hash,
        deployed_at=_utc_now(),
        managed_files=ownership_plan.entries,
    )
    return (
        _SkillManifestWrite(
            path=manifest_path,
            content=manifest.to_json(),
            source_commit=incoming_commit,
            retired_entries=ownership_plan.retired_entries,
        ),
        None,
    )


def plan_skill_manifest_ownership(
    current_targets: Sequence[_RenderedSkillDeploymentTargetLike],
    *,
    chezmoi_home: Path,
    home_root: Path,
    provider_filter: str | None,
    registered_providers: Sequence[str],
) -> tuple[SkillManifestOwnershipPlan | None, str | None]:
    """Return reconciled managed-file state for a skill deployment run."""
    manifest_path = chezmoi_home / SKILLS_MANIFEST_FILENAME
    recorded, read_error = _read_manifest(
        manifest_path,
        chezmoi_home=chezmoi_home,
        home_root=home_root,
    )
    if read_error is not None:
        return None, read_error

    try:
        current_entries = tuple(
            _managed_entry_from_target(
                target,
                chezmoi_home=chezmoi_home,
                home_root=home_root,
            )
            for target in current_targets
        )
        legacy_entries = (
            _discover_legacy_sase_namespace_files(
                chezmoi_home,
                home_root=home_root,
                current_entries=current_entries,
            )
            if provider_filter is None and current_entries
            else ()
        )
        entries = _reconcile_managed_files(
            recorded.managed_files if recorded is not None else (),
            current_entries,
            legacy_entries,
            provider_filter=provider_filter,
            registered_providers=registered_providers,
        )
        _validate_managed_entries(
            entries,
            chezmoi_home=chezmoi_home,
            home_root=home_root,
        )
    except ValueError as exc:
        return None, str(exc)

    retired_entries = tuple(
        entry
        for entry in entries
        if entry.state == "retired" and _entry_in_scope(entry, provider_filter)
    )
    return (
        SkillManifestOwnershipPlan(
            entries=entries,
            retired_entries=retired_entries,
            recorded=recorded,
        ),
        None,
    )


def retired_skill_files_with_drift(
    entries: Sequence[ManagedSkillFile],
    *,
    chezmoi_home: Path,
    home_root: Path,
) -> tuple[ManagedSkillFile, ...]:
    """Return retired tombstones whose source or live target still exists."""
    return tuple(
        entry
        for entry in entries
        if entry.state == "retired"
        and (
            entry.source_path(chezmoi_home).exists()
            or entry.home_path(home_root).exists()
        )
    )


def _read_manifest(
    path: Path,
    *,
    chezmoi_home: Path,
    home_root: Path,
) -> tuple[_SkillDeployManifest | None, str | None]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None, None
    if not isinstance(raw, dict):
        return None, None
    source_commit = raw.get("source_commit")
    xprompt_set_sha256 = raw.get("xprompt_set_sha256")
    deployed_at = raw.get("deployed_at")
    if not isinstance(source_commit, str) or not source_commit:
        return None, None
    if not isinstance(xprompt_set_sha256, str) or not xprompt_set_sha256:
        return None, None
    if not isinstance(deployed_at, str) or not deployed_at:
        return None, None
    managed_files_raw = raw.get("managed_files", [])
    if not isinstance(managed_files_raw, list):
        return None, "skill manifest managed_files must be a list"
    try:
        managed_files = tuple(
            _managed_entry_from_json(
                item,
                chezmoi_home=chezmoi_home,
                home_root=home_root,
            )
            for item in managed_files_raw
        )
        _validate_managed_entries(
            managed_files,
            chezmoi_home=chezmoi_home,
            home_root=home_root,
        )
    except ValueError as exc:
        return None, str(exc)
    return (
        _SkillDeployManifest(
            source_commit=source_commit,
            xprompt_set_sha256=xprompt_set_sha256,
            deployed_at=deployed_at,
            managed_files=managed_files,
        ),
        None,
    )


def _managed_entry_from_target(
    target: _RenderedSkillDeploymentTargetLike,
    *,
    chezmoi_home: Path,
    home_root: Path,
) -> ManagedSkillFile:
    return ManagedSkillFile(
        provider=_non_empty(target.provider, "provider"),
        skill_name=_non_empty(target.skill_name, "skill_name"),
        source_relpath=_relative_posix(chezmoi_home, target.source_path),
        home_relpath=_relative_posix(home_root, target.home_path),
        state="active",
    )


def _managed_entry_from_json(
    raw: object,
    *,
    chezmoi_home: Path,
    home_root: Path,
) -> ManagedSkillFile:
    if not isinstance(raw, dict):
        raise ValueError("skill manifest managed_files entries must be objects")
    provider = raw.get("provider")
    skill_name = raw.get("skill_name")
    source_relpath = raw.get("source_path")
    home_relpath = raw.get("home_path")
    state = raw.get("state", "active")
    if state not in {"active", "retired"}:
        raise ValueError("skill manifest managed file state must be active or retired")
    entry = ManagedSkillFile(
        provider=_non_empty(provider, "provider"),
        skill_name=_non_empty(skill_name, "skill_name"),
        source_relpath=_non_empty(source_relpath, "source_path"),
        home_relpath=_non_empty(home_relpath, "home_path"),
        state=state,
    )
    entry.source_path(chezmoi_home)
    entry.home_path(home_root)
    return entry


def _non_empty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(
            f"skill manifest managed file {field} must be a non-empty string"
        )
    return value


def _relative_posix(root: Path, path: Path) -> str:
    root_resolved = root.resolve(strict=False)
    path_resolved = path.resolve(strict=False)
    try:
        relative = path_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"managed skill path escapes root: {path}") from exc
    return _validate_relative_posix(relative.as_posix())


def _safe_join(root: Path, relative: str) -> Path:
    relative = _validate_relative_posix(relative)
    joined = (root / Path(*PurePosixPath(relative).parts)).resolve(strict=False)
    root_resolved = root.resolve(strict=False)
    try:
        joined.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"managed skill path escapes root: {relative}") from exc
    return joined


def _validate_relative_posix(relative: str) -> str:
    path = PurePosixPath(relative)
    if path.is_absolute():
        raise ValueError(f"managed skill path must be relative: {relative}")
    if ".." in path.parts:
        raise ValueError(f"managed skill path must not contain '..': {relative}")
    if not path.parts or relative in {"", "."}:
        raise ValueError("managed skill path must not be empty")
    return path.as_posix()


def _validate_managed_entries(
    entries: Sequence[ManagedSkillFile],
    *,
    chezmoi_home: Path,
    home_root: Path,
) -> None:
    source_seen: dict[str, ManagedSkillFile] = {}
    home_seen: dict[str, ManagedSkillFile] = {}
    for entry in entries:
        entry.source_path(chezmoi_home)
        entry.home_path(home_root)
        if entry.source_relpath in source_seen:
            raise ValueError(
                "skill manifest has duplicate managed source path: "
                f"{entry.source_relpath}"
            )
        source_seen[entry.source_relpath] = entry
        if entry.home_relpath in home_seen:
            raise ValueError(
                f"skill manifest has duplicate managed home path: {entry.home_relpath}"
            )
        home_seen[entry.home_relpath] = entry


def _reconcile_managed_files(
    recorded_entries: Sequence[ManagedSkillFile],
    current_entries: Sequence[ManagedSkillFile],
    legacy_entries: Sequence[ManagedSkillFile],
    *,
    provider_filter: str | None,
    registered_providers: Sequence[str],
) -> tuple[ManagedSkillFile, ...]:
    del registered_providers
    current_by_key = {
        entry.path_key: entry.with_state("active") for entry in current_entries
    }
    result_by_key: dict[tuple[str, str], ManagedSkillFile] = {}

    if not recorded_entries:
        for entry in current_by_key.values():
            result_by_key[entry.path_key] = entry
    else:
        for entry in recorded_entries:
            if not _entry_in_scope(entry, provider_filter):
                result_by_key[entry.path_key] = entry
                continue
            current = current_by_key.get(entry.path_key)
            if current is not None:
                result_by_key[entry.path_key] = current
                continue
            result_by_key[entry.path_key] = entry.with_state("retired")

        for entry in current_by_key.values():
            if _entry_in_scope(entry, provider_filter):
                result_by_key[entry.path_key] = entry

    if provider_filter is None:
        for entry in legacy_entries:
            result_by_key.setdefault(entry.path_key, entry.with_state("retired"))

    return tuple(sorted(result_by_key.values(), key=lambda entry: entry.sort_key))


def _entry_in_scope(entry: ManagedSkillFile, provider_filter: str | None) -> bool:
    return provider_filter is None or entry.provider == provider_filter


def _discover_legacy_sase_namespace_files(
    chezmoi_home: Path,
    *,
    home_root: Path,
    current_entries: Sequence[ManagedSkillFile],
) -> tuple[ManagedSkillFile, ...]:
    current_keys = {entry.path_key for entry in current_entries}
    entries: list[ManagedSkillFile] = []
    for skill_path in sorted(chezmoi_home.glob("dot_*/**/skills/sase_*/SKILL.md")):
        source_relpath = _relative_posix(chezmoi_home, skill_path)
        source_parts = PurePosixPath(source_relpath).parts
        if not source_parts or not source_parts[0].startswith("dot_"):
            continue
        try:
            skills_index = source_parts.index("skills")
        except ValueError:
            continue
        if skills_index + 2 >= len(source_parts):
            continue
        skill_name = source_parts[skills_index + 1]
        if source_parts[-1] != "SKILL.md" or not skill_name.startswith("sase_"):
            continue
        home_relpath = _chezmoi_relpath_to_home_relpath(source_relpath)
        provider = _legacy_provider_label(source_parts[:skills_index])
        entry = ManagedSkillFile(
            provider=provider,
            skill_name=skill_name,
            source_relpath=source_relpath,
            home_relpath=home_relpath,
            state="retired",
        )
        if entry.path_key in current_keys:
            continue
        entry.source_path(chezmoi_home)
        entry.home_path(home_root)
        entries.append(entry)
    return tuple(entries)


def _chezmoi_relpath_to_home_relpath(source_relpath: str) -> str:
    parts = list(PurePosixPath(source_relpath).parts)
    if not parts or not parts[0].startswith("dot_"):
        raise ValueError(
            f"legacy skill source path is not a dotfile path: {source_relpath}"
        )
    parts[0] = "." + parts[0].removeprefix("dot_")
    return PurePosixPath(*parts).as_posix()


def _legacy_provider_label(prefix_parts: Sequence[str]) -> str:
    if not prefix_parts:
        return "legacy"
    label_parts: list[str] = []
    for index, part in enumerate(prefix_parts):
        if index == 0 and part.startswith("dot_"):
            label_parts.append(part.removeprefix("dot_"))
        else:
            label_parts.append(part)
    return "/".join(label_parts) or "legacy"


def _commit_relation(source_root: Path, *, recorded: str, incoming: str) -> str:
    if _is_ancestor(source_root, recorded, incoming):
        return "fast-forward"
    if _is_ancestor(source_root, incoming, recorded):
        return "backwards"
    return "divergent"


def _is_ancestor(source_root: Path, ancestor: str, descendant: str) -> bool:
    try:
        run_git(
            source_root,
            "merge-base",
            "--is-ancestor",
            ancestor,
            descendant,
        )
    except _GIT_ERRORS:
        return False
    return True


def _refusal_message(
    source_root: Path,
    *,
    recorded: str,
    incoming: str,
    reason: str,
) -> str:
    recorded_subject = _commit_subject(source_root, recorded)
    incoming_subject = _commit_subject(source_root, incoming)
    return (
        f"refusing chezmoi skill deploy because {reason}:\n"
        f"  recorded: {recorded} ({recorded_subject})\n"
        f"  incoming: {incoming} ({incoming_subject})\n"
        f"{_FORCE_INSTRUCTION}"
    )


def _commit_subject(source_root: Path, commit: str) -> str:
    try:
        subject = run_git(source_root, "show", "-s", "--format=%s", commit)
    except _GIT_ERRORS:
        return "subject unavailable"
    return subject or "subject unavailable"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _git_error_detail(exc: BaseException) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        stderr = exc.stderr
        if isinstance(stderr, str) and stderr.strip():
            return stderr.strip()
    return str(exc)
