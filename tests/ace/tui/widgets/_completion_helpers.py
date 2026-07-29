"""Shared helpers for prompt file-completion tests."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
from textual.app import App, ComposeResult

from sase import project_aliases, project_display_names
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
    build_xprompt_assist_entries,
)
from sase.xprompt import project_identity

from tests.main.project_handler_helpers import _disk_project_records, _write_project


class CompletionTestApp(App[None]):
    """Minimal app that hosts PromptInputBar for file completion tests."""

    # Mirror AceApp: the prompt subsystem owns ctrl+n/ctrl+p/ctrl+r, so the
    # command palette (default ctrl+p) must not intercept them.
    ENABLE_COMMAND_PALETTE = False

    def __init__(
        self,
        snippets: dict[str, str] | None = None,
        common_placeholders: list[str] | None = None,
    ) -> None:
        super().__init__()
        self._snippets: dict[str, str] = snippets or {}
        # ``None`` stands in for a cold cache, exactly as the real app's
        # ``common_placeholders()`` does before its first warm lands.
        self._common_placeholders: list[str] | None = common_placeholders
        self._common_placeholders_gen = 0
        self.forgotten_common_placeholders: list[str] = []
        self.forgotten_history_words: list[str] = []
        self.warm_common_requests = 0

    def get_snippets(self) -> dict[str, str]:
        return self._snippets

    def common_placeholders(self) -> list[str] | None:
        return self._common_placeholders

    def common_placeholders_generation(self) -> int:
        return self._common_placeholders_gen

    def publish_common_placeholders(self, placeholders: list[str]) -> None:
        """Stand in for a warm cache landing while a menu is already open."""
        self._common_placeholders = list(placeholders)
        self._common_placeholders_gen += 1

    def forget_common_placeholder(self, text: str) -> None:
        """Mirror the real app cache hook and refresh open placeholder menus."""
        from sase.ace.tui.widgets.placeholder_completion import (
            PLACEHOLDER_COMPLETION_KIND,
        )
        from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

        self.forgotten_common_placeholders.append(text)
        if isinstance(self._common_placeholders, list):
            self._common_placeholders = [
                candidate
                for candidate in self._common_placeholders
                if candidate != text
            ]
        self._common_placeholders_gen += 1
        for text_area in self.query(PromptTextArea):
            if (
                text_area._file_completion_active
                and text_area._completion_kind == PLACEHOLDER_COMPLETION_KIND
            ):
                text_area._refresh_file_completion_from_cursor()

    def warm_common_placeholders(self) -> None:
        self.warm_common_requests += 1

    def forget_history_prompt_word(self, word: str) -> None:
        """Mirror the real app cache hook and refresh open history-word menus."""
        from sase.ace.tui.widgets.history_word_completion import (
            HISTORY_WORD_COMPLETION_KIND,
        )
        from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

        self.forgotten_history_words.append(word)
        words = getattr(self, "words", None)
        if isinstance(words, list):
            words = [candidate for candidate in words if candidate != word]
            self.words = words
        for text_area in self.query(PromptTextArea):
            if (
                text_area._file_completion_active
                and text_area._completion_kind == HISTORY_WORD_COMPLETION_KIND
            ):
                text_area._apply_history_word_completion_result(words or [])

    def compose(self) -> ComposeResult:
        yield PromptInputBar()


class CatalogCompletionTestApp(CompletionTestApp):
    """Completion app whose warm catalog is built from the real xprompt catalog.

    Mirrors the ACE app's memory-only catalog: the widget asks for entries by
    project string and gets a catalog projection built for exactly that string.
    """

    def __init__(self) -> None:
        super().__init__()
        self.requested_projects: list[str | None] = []

    def get_prompt_catalog_assist_entries(
        self,
        project: str | None,
        *,
        schedule: bool = True,
    ) -> list[XPromptAssistEntry]:
        del schedule
        self.requested_projects.append(project)
        return build_xprompt_assist_entries(project=project)


@contextmanager
def registered_project_xprompts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    project_key: str,
    project_name: str,
    xprompts: Mapping[str, str],
) -> Iterator[Path]:
    """Register one project whose directory key differs from its name.

    The project's workspace holds *xprompts* (``name -> body``) under
    ``sase/xprompts/``, so the catalog discovers them through the project
    registry exactly as it does for a real checkout.
    """
    projects_root = tmp_path / "projects"
    projects_root.mkdir(parents=True, exist_ok=True)
    workspace = tmp_path / "workspace"
    xprompt_dir = workspace / "sase" / "xprompts"
    xprompt_dir.mkdir(parents=True, exist_ok=True)
    for name, body in xprompts.items():
        (xprompt_dir / f"{name}.md").write_text(body, encoding="utf-8")

    monkeypatch.setenv("SASE_HOME", str(tmp_path))
    _write_project(
        projects_root,
        project_key,
        "\n".join(
            (
                f"WORKSPACE_DIR: {workspace}",
                "PROJECT_STATE: enabled",
                f"PROJECT_NAME: {project_name}",
            )
        )
        + "\n",
    )
    monkeypatch.setattr(project_aliases, "list_project_records", _disk_project_records)
    monkeypatch.setattr(
        project_display_names,
        "list_project_records",
        _disk_project_records,
    )
    project_identity.invalidate_xprompt_project_identity()

    try:
        with ExitStack() as stack:
            for target, value in (
                ("get_all_xprompts", {}),
                ("get_all_workflows", {}),
                ("get_known_project_workspaces", {project_key: workspace}),
                ("get_sase_package_xprompts_dir", tmp_path / "package"),
                ("get_sase_package_default_xprompts_dir", tmp_path / "defaults"),
            ):
                stack.enter_context(
                    patch(f"sase.xprompt.catalog.{target}", return_value=value)
                )
            yield workspace
    finally:
        project_identity.invalidate_xprompt_project_identity()


def create_entries(root: Path) -> None:
    """Create a deterministic home tree for completion tests."""
    (root / "alpha").mkdir()
    (root / "apple").mkdir()
    (root / "docs").mkdir()
    (root / "readme.md").write_text("x", encoding="utf-8")
    (root / "results.txt").write_text("x", encoding="utf-8")
