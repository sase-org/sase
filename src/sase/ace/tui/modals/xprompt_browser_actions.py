"""Actions mixin for the XPrompt browser modal (edit, add, git commit)."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from sase.ace.hints import build_editor_args
from sase.ace.tui.actions.agent_workflow._prompt_bar_save_xprompt_git import (
    git_index_lock_retry_message,
    run_git_commit_push_sync,
)
from sase.ace.tui.actions.task_actions import (
    TrackedTaskCompletion,
    TrackedTaskResult,
)
from sase.xprompt.config_yaml import insert_xprompt_into_config
from sase.xprompt.loader import get_sase_package_xprompts_dir

from .confirm_action_modal import ConfirmActionModal
from .xprompt_browser_helpers import (
    get_git_root,
    has_git_changes,
    resolve_source_to_file_path,
)


class XPromptBrowserActionsMixin:
    """Mixin providing edit, add, and git commit actions for the browser modal.

    Requires the host class to provide:
    - ``_get_highlighted_item()`` → ``_BrowserItem | None``
    - ``_reload_xprompts()`` → ``None``
    - ``_project`` attribute
    - ``notify()``, ``app`` (from ``ModalScreen``)
    """

    _edit_xprompt_request_id = 0

    def action_edit_xprompt(self) -> None:
        """Schedule loading a simple definition into a bound prompt bar."""
        from sase.ace.tui.modals.xprompt_browser_helpers import is_yaml_backed_source

        item = self._get_highlighted_item()  # type: ignore[attr-defined]
        if item is None:
            return
        if item.kind != "xprompt":
            self.notify("Workflow graphs use E / $EDITOR", severity="warning")  # type: ignore[attr-defined]
            return
        file_path = resolve_source_to_file_path(item.source_path)
        if file_path is None:
            self.notify("Definition source is unavailable", severity="error")  # type: ignore[attr-defined]
            return
        config_backed = is_yaml_backed_source(item.source_path)
        request_id = self._edit_xprompt_request_id + 1
        self._edit_xprompt_request_id = request_id
        self.run_worker(  # type: ignore[attr-defined]
            self._load_xprompt_definition(
                file_path=file_path,
                name=item.name,
                editable=item.is_editable,
                config_backed=config_backed,
                request_id=request_id,
            ),
            exclusive=True,
            group="xprompt-definition-load",
        )

    async def _load_xprompt_definition(
        self,
        *,
        file_path: str,
        name: str,
        editable: bool,
        config_backed: bool,
        request_id: int,
    ) -> None:
        """Read and apply one xprompt definition outside the widget pump."""
        import asyncio

        from sase.ace.tui.widgets.prompt_stack import XPromptBinding
        from sase.xprompt.prompt_frontmatter import PromptFrontmatter
        from sase.xprompt.save import load_config_xprompt_markdown

        try:
            if config_backed:
                markdown = await asyncio.to_thread(
                    load_config_xprompt_markdown, file_path, name
                )
                binding = (
                    XPromptBinding.for_config(
                        file_path,
                        name,
                        reference=f"#{name}",
                    )
                    if editable
                    else None
                )
            else:
                markdown = await asyncio.to_thread(
                    Path(file_path).read_text, encoding="utf-8"
                )
                binding = (
                    XPromptBinding.for_file(file_path, reference=f"#{name}")
                    if editable
                    else None
                )
        except Exception as exc:
            if request_id == self._edit_xprompt_request_id:
                self.notify(f"Could not load definition: {exc}", severity="error")  # type: ignore[attr-defined]
            return

        if request_id != self._edit_xprompt_request_id:
            return
        if not getattr(self, "is_mounted", False):
            return
        loader = getattr(self.app, "load_xprompt_definition_into_home_prompt_bar", None)  # type: ignore[attr-defined]
        if not callable(loader):
            return
        model = PromptFrontmatter.parse(markdown)
        loader(
            markdown,
            display_name=f"#{name}",
            binding=binding,
            read_only=not editable,
            has_comments=model.has_comments,
        )

    def action_external_edit_xprompt(self) -> None:
        """Open highlighted editable definition in ``$EDITOR``."""
        item = self._get_highlighted_item()  # type: ignore[attr-defined]
        if item is None:
            return
        if not item.is_editable:
            self.notify("This xprompt is read-only", severity="warning")  # type: ignore[attr-defined]
            return
        file_path = resolve_source_to_file_path(item.source_path)
        if file_path is None:
            self.notify("Could not resolve source file path", severity="error")  # type: ignore[attr-defined]
            return

        editor = os.environ.get("EDITOR") or "nvim"
        editor_args = build_editor_args(editor, [file_path])

        with self.app.suspend():  # type: ignore[attr-defined]
            subprocess.run(editor_args, check=False)

        self._reload_xprompts()  # type: ignore[attr-defined]
        self._offer_git_commit(file_path, is_new=False, xprompt_name=item.name)

    def action_add_xprompt(self) -> None:
        """Add a new xprompt via location selector then filename input."""
        from .xprompt_config_modal import XPromptConfigEntry, XPromptConfigEntryModal
        from .xprompt_filename_modal import XPromptFilenameModal
        from .xprompt_location_modal import XPromptLocation, XPromptLocationModal

        def _on_location(location: XPromptLocation | None) -> None:
            if location is None:
                return
            if location.location_type == "config":
                # Config file — collect name + inputs via modal, then content
                def _on_config_entry(entry: XPromptConfigEntry | None) -> None:
                    if entry is None:
                        return
                    self._create_config_xprompt(location.path, entry)

                self.app.push_screen(  # type: ignore[attr-defined]
                    XPromptConfigEntryModal(config_path=location.path),
                    _on_config_entry,
                )
            else:
                # Directory location — ask for filename
                def _on_filename(path: str | None) -> None:
                    if path is None:
                        return
                    self._create_and_edit_xprompt(path)

                self.app.push_screen(  # type: ignore[attr-defined]
                    XPromptFilenameModal(directory=location.path), _on_filename
                )

        self.app.push_screen(  # type: ignore[attr-defined]
            XPromptLocationModal(project=self._project),  # type: ignore[attr-defined]
            _on_location,
        )

    def _create_and_edit_xprompt(self, path: str) -> None:
        """Create a skeleton xprompt file and open in editor."""
        expanded = os.path.expanduser(path)
        file_path = Path(expanded)

        file_path.parent.mkdir(parents=True, exist_ok=True)

        if not file_path.exists():
            name = file_path.stem
            if file_path.suffix == ".yml":
                schema_path = get_sase_package_xprompts_dir() / "workflow.schema.json"
                skeleton = (
                    "# yaml-language-server: $schema=" + str(schema_path) + "\n"
                    "\n"
                    "steps:\n"
                    "  - name: main\n"
                    "    prompt: |\n"
                    "      <your prompt here>\n"
                )
            else:
                skeleton = f"# {name}\n\nYour xprompt content here.\n"
            file_path.write_text(skeleton, encoding="utf-8")

        editor = os.environ.get("EDITOR") or "nvim"
        editor_args = build_editor_args(editor, [str(file_path)])

        with self.app.suspend():  # type: ignore[attr-defined]
            subprocess.run(editor_args, check=False)

        self._reload_xprompts()  # type: ignore[attr-defined]
        xprompt_name = file_path.stem
        self._offer_git_commit(str(file_path), is_new=True, xprompt_name=xprompt_name)

    def _create_config_xprompt(
        self,
        config_path: str,
        entry: object,
    ) -> None:
        """Open $EDITOR for content, then insert the xprompt into a config file."""
        from .xprompt_config_modal import XPromptConfigEntry

        assert isinstance(entry, XPromptConfigEntry)

        # Build a helpful template for the editor
        if entry.inputs:
            input_vars = ", ".join(f"{{{{ {n} }}}}" for n, _ in entry.inputs)
            template = f"Your xprompt content here.\n\nAvailable inputs: {input_vars}\n"
        else:
            template = "Your xprompt content here.\n"

        from sase.core.paths import get_sase_managed_tmpdir

        safe_name = entry.name.replace("/", "_")
        tmp_fd, tmp_path = tempfile.mkstemp(
            suffix=".md",
            prefix=f"xprompt_{safe_name}_",
            dir=get_sase_managed_tmpdir("editors"),
        )
        try:
            try:
                os.write(tmp_fd, template.encode("utf-8"))
            finally:
                os.close(tmp_fd)

            editor = os.environ.get("EDITOR") or "nvim"
            editor_args = build_editor_args(editor, [tmp_path])

            with self.app.suspend():  # type: ignore[attr-defined]
                subprocess.run(editor_args, check=False)

            content = Path(tmp_path).read_text(encoding="utf-8")
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        if not content.strip():
            self.notify("Empty content, xprompt not created", severity="warning")  # type: ignore[attr-defined]
            return

        success = insert_xprompt_into_config(
            config_path, entry.name, entry.inputs, content
        )

        if success:
            self.notify(f"Added xprompt '{entry.name}' to config")  # type: ignore[attr-defined]
            self._reload_xprompts()  # type: ignore[attr-defined]
            self._offer_git_commit(config_path, is_new=True, xprompt_name=entry.name)
        else:
            self.notify("Failed to insert xprompt into config", severity="error")  # type: ignore[attr-defined]

    def _offer_git_commit(
        self, file_path: str, *, is_new: bool, xprompt_name: str
    ) -> None:
        """If the file is in a git repo and has changes, offer to commit and push."""
        git_root = get_git_root(file_path)
        if git_root is None:
            return
        if not has_git_changes(git_root, file_path):
            return

        rel_path = os.path.relpath(file_path, git_root)
        verb = "Add" if is_new else "Update"

        def _on_commit_push_answer(confirmed: bool | None) -> None:
            if not confirmed:
                return
            subject = f"chore: {verb} xprompt {xprompt_name}"
            from sase.workflows.commit.runtime_tags import apply_auto_commit_type_tag

            message = apply_auto_commit_type_tag(subject, "xprompt")

            def _task() -> TrackedTaskResult[bool]:
                result = run_git_commit_push_sync(
                    git_root=git_root,
                    file_path=file_path,
                    commit_message=message,
                )
                return TrackedTaskResult(
                    success=result.success,
                    message=result.message,
                    payload=result.index_lock_removed,
                    error=None if result.success else result.message,
                )

            def _on_complete(completion: TrackedTaskCompletion[bool]) -> None:
                severity = "information" if completion.success else "error"
                self.notify(completion.message, severity=severity)  # type: ignore[attr-defined]
                if completion.payload:
                    self.notify(  # type: ignore[attr-defined]
                        git_index_lock_retry_message(git_root),
                        severity="warning",
                    )

            submit = getattr(self.app, "_submit_tracked_task", None)  # type: ignore[attr-defined]
            if not callable(submit):
                self.notify(  # type: ignore[attr-defined]
                    "Could not commit xprompt: background task queue unavailable.",
                    severity="error",
                )
                return
            submit(
                "xprompt-commit",
                rel_path,
                git_root,
                _task,
                display_name=f"commit xprompt {rel_path}",
                dedup_key=f"xprompt-commit:{git_root}:{rel_path}",
                duplicate_message=(
                    f"Another xprompt commit is already running for {rel_path}."
                ),
                on_complete=_on_complete,
                reload_on_complete=False,
                notify_on_complete=False,
            )

        self.app.push_screen(  # type: ignore[attr-defined]
            ConfirmActionModal(
                "Commit & Push",
                "Commit and push your xprompt changes?",
                subject=rel_path,
                icon="↑",
                confirm_label="Commit & push",
                cancel_label="Skip",
                default="confirm",
            ),
            _on_commit_push_answer,
        )
