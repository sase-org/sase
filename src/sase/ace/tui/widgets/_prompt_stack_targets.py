"""Source metadata for editable prompt-stack targets."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Literal

from sase.xprompt.save import SaveTargetFormat


@dataclass(frozen=True)
class SourceFingerprint:
    """Disk identity used to reject silent writes over external changes."""

    mtime_ns: int
    size: int
    content_hash: str

    @classmethod
    def from_path(cls, path: str | Path) -> SourceFingerprint:
        source = Path(path)
        data = source.read_bytes()
        stat = source.stat()
        return cls(stat.st_mtime_ns, stat.st_size, hashlib.sha256(data).hexdigest())

    @staticmethod
    def stat_signature(path: str | Path) -> tuple[int, int] | None:
        """Return a cheap ``(mtime_ns, size)`` signature for display staleness."""
        try:
            stat = Path(path).stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def matches_stat(self, path: str | Path) -> bool:
        """Return whether *path* still has this fingerprint's stat metadata."""
        return self.stat_signature(path) == (self.mtime_ns, self.size)


@dataclass(frozen=True)
class XPromptBinding:
    """The editable xprompt source a prompt stack writes back to."""

    kind: Literal["file", "config"]
    path: str
    write_path: str
    apply_target: str | None
    via_chezmoi: bool
    reference: str
    target_format: SaveTargetFormat
    loaded_fingerprint: SourceFingerprint
    entry_name: str | None = None

    @classmethod
    def for_file(
        cls,
        path: str | Path,
        *,
        reference: str | None = None,
    ) -> XPromptBinding:
        from sase.xprompt.write_targets import (
            canonical_reference_for_path,
            resolve_xprompt_write_target,
        )

        target = resolve_xprompt_write_target(path)
        return cls(
            kind="file",
            path=str(target.read_path),
            write_path=str(target.write_path),
            apply_target=(
                str(target.apply_target) if target.apply_target is not None else None
            ),
            via_chezmoi=target.via_chezmoi,
            reference=canonical_reference_for_path(
                target.read_path,
                write_path=target.write_path,
                reference=reference,
            ),
            target_format=SaveTargetFormat.MARKDOWN,
            loaded_fingerprint=SourceFingerprint.from_path(target.write_path),
        )

    @classmethod
    def for_config(
        cls,
        path: str | Path,
        entry_name: str,
        *,
        reference: str | None = None,
    ) -> XPromptBinding:
        from sase.xprompt.write_targets import (
            canonical_reference_for_path,
            resolve_xprompt_write_target,
        )

        target = resolve_xprompt_write_target(path)
        return cls(
            kind="config",
            path=str(target.read_path),
            write_path=str(target.write_path),
            apply_target=(
                str(target.apply_target) if target.apply_target is not None else None
            ),
            via_chezmoi=target.via_chezmoi,
            reference=canonical_reference_for_path(
                target.read_path,
                write_path=target.write_path,
                entry_name=entry_name,
                reference=reference,
            ),
            target_format=SaveTargetFormat.CONFIG,
            loaded_fingerprint=SourceFingerprint.from_path(target.write_path),
            entry_name=entry_name,
        )

    @property
    def name(self) -> str:
        return self.entry_name or Path(self.path).stem


@dataclass(frozen=True)
class XPromptReadonlyTarget:
    """A loaded xprompt definition that can be inspected but not overwritten."""

    reference: str
    path: str | None = None


@dataclass(frozen=True)
class SnippetPaneTarget:
    """The snippet definition a pane-scoped snippet draft writes back to."""

    trigger: str
    read_path: str
    write_path: str
    display_path: str
    apply_target: str | None
    via_chezmoi: bool
    exists: bool
    loaded_body: str | None
    loaded_fingerprint: SourceFingerprint | None
    derived_from: str | None = None
    save_warning: str | None = None


def mini_xprompt_draft_hash(frontmatter: str, body: str) -> str:
    """Return the stable dirty-check hash for one mini-xprompt draft."""
    payload = f"{frontmatter}\0{body.strip()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MiniXPromptPaneTarget:
    """The xprompt definition a pane-scoped mini-xprompt draft edits."""

    name: str
    reference: str
    location_path: str
    read_path: str
    write_path: str
    display_path: str
    apply_target: str | None
    via_chezmoi: bool
    target_format: SaveTargetFormat
    entry_name: str | None
    storage_name: str
    exists: bool
    frontmatter: str
    loaded_body: str | None
    loaded_markdown: str | None
    loaded_fingerprint: SourceFingerprint | None
    clean_hash: str
    derived_from: str | None = None
    save_warning: str | None = None

    def draft_hash(self, body: str) -> str:
        """Return the dirty-check hash for *body* under this target frontmatter."""
        return mini_xprompt_draft_hash(self.frontmatter, body)


__all__ = [
    "MiniXPromptPaneTarget",
    "SnippetPaneTarget",
    "SourceFingerprint",
    "XPromptBinding",
    "XPromptReadonlyTarget",
    "mini_xprompt_draft_hash",
]
