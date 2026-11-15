"""PromptTextArea preview command mixin."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sase.ace.tui.widgets._prompt_preview_target import (
    PreviewError,
    PreviewToken,
    detect_preview_target_at_cursor,
    detect_shorthand_argument_owner_at_cursor,
    is_slash_skill_candidate_at_cursor,
    resolve_preview_target,
)
from sase.core.word_lookup import WordSpan, extract_lookup_word

if TYPE_CHECKING:
    from textual.widgets import TextArea as _MixinBase
else:
    _MixinBase = object


@dataclass(frozen=True)
class PreviewFallbackSnapshot:
    """Keypress-time state for resuming the K chain after the bead step."""

    text: str
    offset: int
    word_span: WordSpan | None
    shorthand_token: PreviewToken | None
    project: str | None
    base_dir: str
    cursor: tuple[int, int]


class PromptPreviewMixin(_MixinBase):
    """Normal-mode preview command for macros, skills, workflows, and files."""

    if TYPE_CHECKING:
        _prompt_preview_request_id: int

        def _absolute_offset(self, location: tuple[int, int]) -> int: ...
        def _get_warm_macro_skill_names_if_available(
            self,
        ) -> frozenset[str] | None: ...
        def _schedule_macro_assist_warm(self, project: str | None) -> None: ...
        def _macro_arg_assist_project_from_text(self) -> str | None: ...
        def _lookup_word_under_cursor(
            self,
            span: WordSpan | None = None,
            *,
            bead_miss: str | None = None,
        ) -> bool: ...
        def _preview_glossary_under_cursor(self) -> bool: ...
        def _preview_repo_mention_under_cursor(self) -> bool: ...
        def _preview_bead_under_cursor(
            self, fallback: PreviewFallbackSnapshot
        ) -> bool: ...

    def _preview_token_under_cursor(self) -> None:
        """Resolve and open a preview for the token under the cursor."""
        offset = self._absolute_offset(self.cursor_location)
        known_skills = self._known_slash_skills_for_action(offset)
        if known_skills is None:
            return
        token = detect_preview_target_at_cursor(
            self.text,
            offset,
            known_skills=known_skills,
        )
        if token is None:
            preview_glossary = getattr(self, "_preview_glossary_under_cursor", None)
            if callable(preview_glossary) and preview_glossary():
                return
            preview_repo_mention = getattr(
                self, "_preview_repo_mention_under_cursor", None
            )
            if callable(preview_repo_mention) and preview_repo_mention():
                return
            fallback = self._capture_preview_fallback_snapshot(offset)
            preview_bead = getattr(self, "_preview_bead_under_cursor", None)
            if callable(preview_bead) and preview_bead(fallback):
                return
            self._resume_preview_fallback(fallback)
            return

        project, base_dir = self._preview_context()
        self._prompt_preview_request_id += 1
        request_id = self._prompt_preview_request_id
        self.run_worker(
            self._resolve_preview_async(
                token,
                project=project,
                base_dir=base_dir,
                request_id=request_id,
            ),
            name=f"prompt-preview:{request_id}",
        )

    def _capture_preview_fallback_snapshot(
        self,
        offset: int,
    ) -> PreviewFallbackSnapshot:
        row, col = self.cursor_location
        project, base_dir = self._preview_context()
        return PreviewFallbackSnapshot(
            text=self.text,
            offset=offset,
            word_span=extract_lookup_word(self.document.get_line(row), row, col),
            shorthand_token=detect_shorthand_argument_owner_at_cursor(
                self.text, offset
            ),
            project=project,
            base_dir=base_dir,
            cursor=self.cursor_location,
        )

    def _resume_preview_fallback(
        self,
        snapshot: PreviewFallbackSnapshot,
        *,
        bead_miss: str | None = None,
    ) -> None:
        """Resume word lookup → shorthand owner → warning from *snapshot*."""
        if snapshot.word_span is not None and self._lookup_word_under_cursor(
            snapshot.word_span,
            bead_miss=bead_miss,
        ):
            return
        token = snapshot.shorthand_token
        if token is not None:
            self._prompt_preview_request_id += 1
            request_id = self._prompt_preview_request_id
            self.run_worker(
                self._resolve_preview_async(
                    token,
                    project=snapshot.project,
                    base_dir=snapshot.base_dir,
                    request_id=request_id,
                ),
                name=f"prompt-preview:{request_id}",
            )
            return
        if bead_miss:
            self.notify(bead_miss, severity="information")
            return
        self.notify(
            "Move the cursor onto a macro, skill, file path, glossary "
            "term, repo name, bead ID, or word to look it up",
            severity="warning",
        )

    async def _resolve_preview_async(
        self,
        token: PreviewToken,
        *,
        project: str | None,
        base_dir: str,
        request_id: int,
    ) -> None:
        try:
            payload = await asyncio.to_thread(
                resolve_preview_target,
                token,
                project=project,
                base_dir=base_dir,
            )
        except PreviewError as exc:
            if request_id == self._prompt_preview_request_id and self.is_mounted:
                self.notify(str(exc), severity="warning")
            return
        except Exception as exc:
            if request_id == self._prompt_preview_request_id and self.is_mounted:
                self.notify(f"Could not preview {token.raw}: {exc}", severity="error")
            return

        if request_id != self._prompt_preview_request_id or not self.is_mounted:
            return

        if payload.media == "image":
            from sase.ace.tui.modals.preview_panel_image_modal import (
                ImagePreviewPanelModal,
            )

            self.app.push_screen(ImagePreviewPanelModal(payload))
            return

        from sase.ace.tui.modals.preview_panel_modal import PreviewPanelModal

        self.app.push_screen(PreviewPanelModal(payload))

    def _known_slash_skills_for_action(
        self,
        cursor_offset: int,
    ) -> frozenset[str] | None:
        """Return warm slash skills, or defer an ambiguous cold lookup."""
        if "/" not in self.text:
            return frozenset()
        known_skills = self._get_warm_macro_skill_names_if_available()
        if known_skills is not None:
            return known_skills
        if not is_slash_skill_candidate_at_cursor(self.text, cursor_offset):
            return frozenset()
        project = self._macro_arg_assist_project_from_text()
        self._schedule_macro_assist_warm(project)
        self.notify(
            "Skill catalog is still loading; try again",
            severity="warning",
        )
        return None

    def _preview_context(self) -> tuple[str | None, str]:
        """Return ``(project, base_dir)`` for preview resolution."""
        project = self._macro_arg_assist_project_from_text()
        base_dir = os.getcwd()
        ctx = getattr(self.app, "_prompt_context", None)
        if ctx is None:
            return project, base_dir

        is_home_mode = bool(getattr(ctx, "is_home_mode", False))
        workspace_dir = getattr(ctx, "workspace_dir", "")
        if isinstance(workspace_dir, str) and workspace_dir:
            base_dir = workspace_dir
        elif is_home_mode:
            base_dir = str(Path.home())
        return project, base_dir


__all__ = ["PreviewFallbackSnapshot", "PromptPreviewMixin"]
