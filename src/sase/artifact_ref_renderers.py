"""Jinja protection helpers for rendered artifact-reference replacement text."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ArtifactRendererJinjaProtection:
    """Protect Jinja delimiters emitted by artifact renderers."""

    replacements: list[tuple[str, str]] = field(default_factory=list)

    def protect(self, text: str) -> str:
        protected = text
        for delimiter in _JINJA_DELIMITERS:
            while delimiter in protected:
                placeholder = f"\x00SASE_ARTIFACT_JINJA_{len(self.replacements)}\x00"
                self.replacements.append((placeholder, delimiter))
                protected = protected.replace(delimiter, placeholder, 1)
        return protected

    def unprotect(self, text: str) -> str:
        restored = text
        for placeholder, delimiter in reversed(self.replacements):
            restored = restored.replace(placeholder, delimiter)
        return restored


_JINJA_DELIMITERS = ("{{", "}}", "{%", "%}", "{#", "#}")


__all__ = [
    "ArtifactRendererJinjaProtection",
]
