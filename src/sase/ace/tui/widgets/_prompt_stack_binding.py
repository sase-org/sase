"""Bound-source persistence behavior for the prompt-stack state model."""

from __future__ import annotations

import hashlib

from sase.xprompt.prompt_frontmatter import PromptFrontmatter

from ._prompt_stack_parsing import split_frontmatter
from ._prompt_stack_targets import SourceFingerprint, XPromptBinding


class PromptStackBindingMixin:
    """Track dirty state and source identity for an editable xprompt binding."""

    binding: XPromptBinding | None
    _clean_content_hash: str | None
    _bound_source_markdown: str | None
    _bound_source_texts: tuple[str, ...] | None

    @property
    def texts(self) -> list[str]:
        """Agent prompt texts supplied by the concrete stack model."""
        raise NotImplementedError

    def join(self, *, include_frontmatter: bool = True) -> str:
        """Render launch text using the concrete stack model."""
        raise NotImplementedError

    @property
    def is_dirty(self) -> bool:
        """Whether a bound stack differs from its last loaded/written form."""
        if self.binding is None or self._clean_content_hash is None:
            return False
        return self._draft_hash() != self._clean_content_hash

    def bind(
        self, binding: XPromptBinding, *, source_markdown: str | None = None
    ) -> None:
        self.binding = binding
        self._clean_content_hash = self._draft_hash()
        self._bound_source_markdown = source_markdown
        self._bound_source_texts = (
            tuple(self.texts) if source_markdown is not None else None
        )

    def unbind(self) -> None:
        self.binding = None
        self._clean_content_hash = None
        self._bound_source_markdown = None
        self._bound_source_texts = None

    def source_changed(self) -> bool:
        binding = self.binding
        if binding is None:
            return False
        try:
            return (
                SourceFingerprint.from_path(binding.write_path)
                != binding.loaded_fingerprint
            )
        except OSError:
            return True

    def source_stat_changed(self) -> bool:
        """Return a cheap staleness hint without reading source bytes."""
        binding = self.binding
        if binding is None:
            return False
        return not binding.loaded_fingerprint.matches_stat(binding.write_path)

    def mark_written(
        self,
        *,
        source_markdown: str | None = None,
        loaded_fingerprint: SourceFingerprint | None = None,
    ) -> None:
        binding = self.binding
        if binding is None:
            return
        if loaded_fingerprint is None:
            loaded_fingerprint = SourceFingerprint.from_path(binding.write_path)
        self.binding = XPromptBinding(
            kind=binding.kind,
            path=binding.path,
            write_path=binding.write_path,
            apply_target=binding.apply_target,
            via_chezmoi=binding.via_chezmoi,
            reference=binding.reference,
            target_format=binding.target_format,
            entry_name=binding.entry_name,
            loaded_fingerprint=loaded_fingerprint,
        )
        self._clean_content_hash = self._draft_hash()
        if source_markdown is not None:
            self._bound_source_markdown = source_markdown
            self._bound_source_texts = tuple(self.texts)

    def markdown_preserving_unchanged_body(
        self, frontmatter: PromptFrontmatter
    ) -> str | None:
        """Replace only frontmatter when a bound Markdown body is untouched."""
        source = self._bound_source_markdown
        if source is None or self._bound_source_texts != tuple(self.texts):
            return None
        old_frontmatter, _ = split_frontmatter(source)
        new_frontmatter = frontmatter.serialize()
        if old_frontmatter:
            remainder = source[len(old_frontmatter) :]
            return (
                new_frontmatter + remainder
                if new_frontmatter
                else remainder.lstrip("\r\n")
            )
        if new_frontmatter:
            return f"{new_frontmatter}\n\n{source}"
        return source

    def _draft_hash(self) -> str:
        return hashlib.sha256(self.join().encode("utf-8")).hexdigest()


__all__ = ["PromptStackBindingMixin"]
