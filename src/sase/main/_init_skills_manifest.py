"""Provenance manifest and monotonicity checks for skill deployments."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import subprocess

from sase.version._git import run_git
from sase.xprompt.loader import get_sase_package_xprompts_dir
from sase.xprompt.models import XPrompt

SKILLS_MANIFEST_FILENAME = ".sase-skills-manifest.json"

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


@dataclass(frozen=True)
class _SkillDeployManifest:
    """Provenance for the generated skill set in the chezmoi repository."""

    source_commit: str
    xprompt_set_sha256: str
    deployed_at: str

    def to_json(self) -> str:
        """Return the stable, version-controlled JSON representation."""
        return (
            json.dumps(
                {
                    "deployed_at": self.deployed_at,
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


def _skill_xprompt_set_sha256(skill_xprompts: Sequence[XPrompt]) -> str:
    """Hash the selected xprompt fields that determine generated skill content."""
    entries = [
        {
            "content": xprompt.content,
            "description": xprompt.description or "",
            "log_skill_use": xprompt.log_skill_use,
            "name": xprompt.name,
            "skill": xprompt.skill,
        }
        for xprompt in sorted(skill_xprompts, key=lambda item: item.name)
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
) -> tuple[_SkillManifestWrite | None, str | None]:
    """Prepare a manifest write or return a pre-write refusal message."""
    manifest_path = chezmoi_home / SKILLS_MANIFEST_FILENAME
    try:
        source_root = Path(
            run_git(
                get_sase_package_xprompts_dir().resolve(),
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
    recorded = _read_manifest(manifest_path)
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
    ):
        return _SkillManifestWrite(path=manifest_path, content=None), None

    manifest = _SkillDeployManifest(
        source_commit=incoming_commit,
        xprompt_set_sha256=incoming_hash,
        deployed_at=_utc_now(),
    )
    return _SkillManifestWrite(path=manifest_path, content=manifest.to_json()), None


def _read_manifest(path: Path) -> _SkillDeployManifest | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    source_commit = raw.get("source_commit")
    xprompt_set_sha256 = raw.get("xprompt_set_sha256")
    deployed_at = raw.get("deployed_at")
    if not isinstance(source_commit, str) or not source_commit:
        return None
    if not isinstance(xprompt_set_sha256, str) or not xprompt_set_sha256:
        return None
    if not isinstance(deployed_at, str) or not deployed_at:
        return None
    return _SkillDeployManifest(
        source_commit=source_commit,
        xprompt_set_sha256=xprompt_set_sha256,
        deployed_at=deployed_at,
    )


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
