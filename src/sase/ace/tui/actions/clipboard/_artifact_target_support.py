"""Shared selection and delivery support for artifact copy targets."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ...widgets.artifacts.entry_navigation import ArtifactEntryTarget
from ._base import ClipboardBase
from ._delivery import schedule_copy_delivery
from ._helpers import cap_copy_content, format_multi_copy_content_capped


class ClipboardArtifactTargetSupportMixin(ClipboardBase):
    """Resolve visible marks and deliver bounded artifact copy content."""

    def _visible_marked_targets(
        self,
        pane: Any,
    ) -> tuple[ArtifactEntryTarget, ...] | None:
        """Return marked targets in visible row order, or None when unmarked."""
        all_marks = getattr(self, "_artifacts_marked_targets", {})
        marks = all_marks.get(self.current_artifacts_pane_key, set())
        if not marks:
            return None
        if pane is None:
            return ()
        targets = tuple(target for target in pane.entry_targets() if target in marks)
        if not targets:
            self.notify(  # type: ignore[attr-defined]
                f"No marked {self.current_artifacts_pane_key} entries are visible",
                severity="warning",
            )
        return targets

    def _schedule_marked_copy(
        self,
        contents: list[tuple[str, str | Callable[[], str]]],
        *,
        plural_label: str,
        task_name: str = "sase-artifacts-copy-marked",
        unavailable_count: int = 0,
    ) -> None:
        """Resolve a marked set off-thread and format it consistently."""
        if not contents:
            self.notify(  # type: ignore[attr-defined]
                "No marked entries are available to copy",
                severity="warning",
            )
            return

        state = {"successes": 0, "failures": 0, "truncated": False}

        def resolve() -> str:
            values: list[tuple[str, str]] = []
            errors: list[Exception] = []
            for name, content in contents:
                try:
                    values.append((name, content() if callable(content) else content))
                except Exception as exc:
                    errors.append(exc)
            if not values:
                if errors:
                    raise errors[0]
                raise ValueError("No marked entries are available to copy")
            capped = format_multi_copy_content_capped(values)
            state.update(
                successes=len(values),
                failures=unavailable_count + len(errors),
                truncated=capped.truncated,
            )
            return capped.value

        def copied_message() -> str:
            message = f"Copied {state['successes']} {plural_label}"
            if state["failures"]:
                noun = "entry" if state["failures"] == 1 else "entries"
                message += f" — {state['failures']} {noun} unavailable"
            if state["truncated"]:
                message += " — truncated"
            return message

        self._schedule_artifacts_copy(
            resolve,
            copied_message=copied_message,
            task_name=task_name,
        )

    def _schedule_artifacts_copy(
        self,
        content: str | Callable[[], str],
        *,
        copied_message: str | Callable[[], str],
        task_name: str = "sase-artifacts-copy",
        content_shaped: bool = False,
    ) -> None:
        """Resolve and copy content without blocking Textual's message pump."""
        value = content
        state = {"truncated": False}
        if content_shaped:

            def bounded_value() -> str:
                resolved = content() if callable(content) else content
                capped = cap_copy_content(resolved)
                state["truncated"] = capped.truncated
                return capped.value

            value = bounded_value

        def copied_label() -> str:
            message = copied_message() if callable(copied_message) else copied_message
            label = message.removeprefix("Copied ")
            return f"{label} — truncated" if state["truncated"] else label

        schedule_copy_delivery(
            self,
            value,
            copied_label=copied_label,
            task_name=task_name,
        )


__all__ = ["ClipboardArtifactTargetSupportMixin"]
