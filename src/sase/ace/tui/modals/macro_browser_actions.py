"""Actions mixin for the Macro browser modal (edit, add, git commit)."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from sase.ace.hints import build_editor_args
from sase.ace.tui.actions.agent_workflow._prompt_bar_save_macro_git import (
    submit_post_write_action_sequence,
)
from sase.macro.config_yaml import insert_macro_into_config
from sase.macro.loader import get_sase_package_macros_dir
from sase.macro.reference_display import SIMPLE_MACRO_KIND_VALUE
from sase.macro.write_targets import (
    PostWriteActionKind,
    PostWriteActionOffer,
    MacroWriteTarget,
    build_post_write_action_offers,
    classify_written_file,
    write_target_for_written_path,
)

from .post_write_actions_modal import PostWriteActionsModal
from .macro_browser_helpers import (
    resolve_source_to_file_path,
)


class MacroBrowserActionsMixin:
    """Mixin providing edit, add, and git commit actions for the browser modal.

    Requires the host class to provide:
    - ``_get_highlighted_item()`` → ``_BrowserItem | None``
    - ``_reload_macros()`` → ``None``
    - ``_project`` attribute
    - ``notify()``, ``app`` (from ``ModalScreen``)
    """

    _edit_macro_request_id = 0

    def action_edit_macro(self) -> None:
        """Schedule loading a simple definition into a bound prompt bar."""
        item = self._get_highlighted_item()  # type: ignore[attr-defined]
        if item is None:
            return
        if item.kind != SIMPLE_MACRO_KIND_VALUE:
            self.notify("Workflow graphs use E / $EDITOR", severity="warning")  # type: ignore[attr-defined]
            return
        file_path = resolve_source_to_file_path(item.source_path)
        if file_path is None:
            self.notify("Definition source is unavailable", severity="error")  # type: ignore[attr-defined]
            return
        request_id = self._edit_macro_request_id + 1
        self._edit_macro_request_id = request_id
        self.run_worker(  # type: ignore[attr-defined]
            self._load_macro_definition(
                name=item.name,
                source_path=item.source_path,
                editable=item.is_editable,
                reference=item.insertion,
                request_id=request_id,
            ),
            exclusive=True,
            group="macro-definition-load",
        )

    async def _load_macro_definition(
        self,
        *,
        name: str,
        source_path: str | None,
        editable: bool,
        reference: str,
        request_id: int,
    ) -> None:
        """Read and apply one macro definition outside the widget pump."""
        from .macro_definition_loader import load_macro_definition_for_prompt_bar

        try:
            loaded = await load_macro_definition_for_prompt_bar(
                name=name,
                source_path=source_path,
                editable=editable,
                reference=reference,
            )
        except Exception as exc:
            if request_id == self._edit_macro_request_id:
                self.notify(f"Could not load definition: {exc}", severity="error")  # type: ignore[attr-defined]
            return

        if request_id != self._edit_macro_request_id:
            return
        if not getattr(self, "is_mounted", False):
            return
        loader = getattr(self.app, "load_macro_definition_into_home_prompt_bar", None)  # type: ignore[attr-defined]
        if not callable(loader):
            return
        loader(
            loaded.markdown,
            display_name=loaded.display_name,
            binding=loaded.binding,
            read_only=loaded.read_only,
            read_only_path=loaded.read_only_path,
            has_comments=loaded.has_comments,
        )

    def action_external_edit_macro(self) -> None:
        """Open highlighted editable definition in ``$EDITOR``."""
        item = self._get_highlighted_item()  # type: ignore[attr-defined]
        if item is None:
            return
        if not item.is_editable:
            self.notify("This macro is read-only", severity="warning")  # type: ignore[attr-defined]
            return
        file_path = resolve_source_to_file_path(item.source_path)
        if file_path is None:
            self.notify("Could not resolve source file path", severity="error")  # type: ignore[attr-defined]
            return

        editor = os.environ.get("EDITOR") or "nvim"
        editor_args = build_editor_args(editor, [file_path])

        with self.app.suspend():  # type: ignore[attr-defined]
            subprocess.run(editor_args, check=False)

        self._reload_macros()  # type: ignore[attr-defined]
        self._offer_git_commit(file_path, is_new=False, macro_name=item.name)

    def action_add_macro(self) -> None:
        """Add a new macro via location selector then filename input."""
        from .macro_config_modal import MacroConfigEntry, MacroConfigEntryModal
        from .macro_filename_modal import MacroFilenameModal
        from .macro_location_modal import MacroLocation, MacroLocationModal

        def _on_location(location: MacroLocation | None) -> None:
            if location is None:
                return
            if location.location_type == "config":
                # Config file — collect name + inputs via modal, then content
                def _on_config_entry(entry: MacroConfigEntry | None) -> None:
                    if entry is None:
                        return
                    self._create_config_macro(location.path, entry)

                self.app.push_screen(  # type: ignore[attr-defined]
                    MacroConfigEntryModal(config_path=location.path),
                    _on_config_entry,
                )
            else:
                # Directory location — ask for filename
                def _on_filename(path: str | None) -> None:
                    if path is None:
                        return
                    self._create_and_edit_macro(path)

                self.app.push_screen(  # type: ignore[attr-defined]
                    MacroFilenameModal(directory=location.path), _on_filename
                )

        self.app.push_screen(  # type: ignore[attr-defined]
            MacroLocationModal(project=self._project),  # type: ignore[attr-defined]
            _on_location,
        )

    def _create_and_edit_macro(self, path: str) -> None:
        """Create a skeleton macro file and open in editor."""
        expanded = os.path.expanduser(path)
        file_path = Path(expanded)

        file_path.parent.mkdir(parents=True, exist_ok=True)

        if not file_path.exists():
            name = file_path.stem
            if file_path.suffix == ".yml":
                schema_path = get_sase_package_macros_dir() / "workflow.schema.json"
                skeleton = (
                    "# yaml-language-server: $schema=" + str(schema_path) + "\n"
                    "\n"
                    "steps:\n"
                    "  - name: main\n"
                    "    prompt: |\n"
                    "      <your prompt here>\n"
                )
            else:
                skeleton = f"# {name}\n\nYour macro content here.\n"
            file_path.write_text(skeleton, encoding="utf-8")

        editor = os.environ.get("EDITOR") or "nvim"
        editor_args = build_editor_args(editor, [str(file_path)])

        with self.app.suspend():  # type: ignore[attr-defined]
            subprocess.run(editor_args, check=False)

        self._reload_macros()  # type: ignore[attr-defined]
        macro_name = file_path.stem
        self._offer_git_commit(str(file_path), is_new=True, macro_name=macro_name)

    def _create_config_macro(
        self,
        config_path: str,
        entry: object,
    ) -> None:
        """Open $EDITOR for content, then insert the macro into a config file."""
        from .macro_config_modal import MacroConfigEntry

        assert isinstance(entry, MacroConfigEntry)

        # Build a helpful template for the editor
        if entry.inputs:
            input_vars = ", ".join(f"{{{{ {n} }}}}" for n, _ in entry.inputs)
            template = f"Your macro content here.\n\nAvailable inputs: {input_vars}\n"
        else:
            template = "Your macro content here.\n"

        from sase.core.paths import get_sase_managed_tmpdir

        safe_name = entry.name.replace("/", "_")
        tmp_fd, tmp_path = tempfile.mkstemp(
            suffix=".md",
            prefix=f"macro_{safe_name}_",
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
            self.notify("Empty content, macro not created", severity="warning")  # type: ignore[attr-defined]
            return

        success = insert_macro_into_config(
            config_path, entry.name, entry.inputs, content
        )

        if success:
            self.notify(f"Added macro '{entry.name}' to config")  # type: ignore[attr-defined]
            self._reload_macros()  # type: ignore[attr-defined]
            self._offer_git_commit(config_path, is_new=True, macro_name=entry.name)
        else:
            self.notify("Failed to insert macro into config", severity="error")  # type: ignore[attr-defined]

    def _offer_git_commit(
        self, file_path: str, *, is_new: bool, macro_name: str
    ) -> None:
        """Schedule post-write follow-up probing for *file_path*."""
        self.run_worker(  # type: ignore[attr-defined]
            self._offer_post_write_actions_for_file(
                file_path,
                is_new=is_new,
                macro_name=macro_name,
            ),
            exclusive=True,
            group="macro-post-write-actions",
        )

    async def _offer_post_write_actions_for_file(
        self,
        file_path: str,
        *,
        is_new: bool,
        macro_name: str,
    ) -> None:
        """Build and push post-write actions without blocking the TUI pump."""
        import asyncio

        target, offers = await asyncio.to_thread(
            _build_post_write_actions_for_file,
            file_path,
            is_new=is_new,
            macro_name=macro_name,
        )
        if not getattr(self, "is_mounted", False):
            return
        if not offers:
            return
        by_kind = {offer.kind: offer for offer in offers}

        def _on_actions_selected(
            selected: tuple[PostWriteActionKind, ...] | None,
        ) -> None:
            if not selected:
                return
            selected_offers = tuple(
                by_kind[kind] for kind in selected if kind in by_kind
            )
            submit_post_write_action_sequence(
                self,
                self.app,  # type: ignore[attr-defined]
                selected_offers,
                noun="macro",
            )

        subject = offers[0].rel_path
        if target.via_chezmoi and target.apply_target is not None:
            subject = f"{subject}\nchezmoi source for {target.apply_target}"
        self.app.push_screen(  # type: ignore[attr-defined]
            PostWriteActionsModal(offers, subject=subject),
            _on_actions_selected,
        )


def _build_post_write_actions_for_file(
    file_path: str,
    *,
    is_new: bool,
    macro_name: str,
) -> tuple[MacroWriteTarget, tuple[PostWriteActionOffer, ...]]:
    target = write_target_for_written_path(file_path)
    kind = classify_written_file(target.write_path, read_path=target.read_path)
    offers = build_post_write_action_offers(
        target,
        kind=kind,
        is_new=is_new,
        macro_name=macro_name,
    )
    return target, offers
