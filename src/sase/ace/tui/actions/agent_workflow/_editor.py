"""Editor integration for agent workflow (external editor, workflow YAML)."""

from __future__ import annotations

import logging
import os

from sase.editor_resolver import resolve_editor


log = logging.getLogger(__name__)


def _read_editor_file(path: str) -> str | None:
    """Read an editor scratch file, returning None when it cannot be recovered."""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeError):
        return None


def _unlink_editor_file(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


class EditorMixin:
    """Mixin providing editor integration for agent prompts and workflows."""

    _prompt_editor_suspended: bool

    def _open_editor_for_agent_prompt(
        self,
        initial_content: str = "",
        cursor_row: int = 0,
        cursor_col: int = 0,
        *,
        cursor_position: int = 0,
    ) -> str | None:
        """Suspend TUI and open editor for prompt input.

        Args:
            initial_content: Initial text to populate the editor with.
            cursor_row: Cursor row (0-indexed).
            cursor_col: Cursor column (0-indexed).
            cursor_position: Legacy flat cursor offset (used when row/col
                are both 0 but a flat offset was provided).

        Returns:
            The prompt content, or None if empty/cancelled.
        """
        import subprocess
        import tempfile

        def run_editor() -> str | None:
            from sase.core.paths import get_sase_managed_tmpdir

            fd, temp_path = tempfile.mkstemp(
                suffix=".md",
                prefix="sase_ace_prompt_",
                dir=get_sase_managed_tmpdir("editors"),
            )
            # Write initial content if provided
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(initial_content)

            editor = resolve_editor()
            cmd: list[str] = list(editor.argv)
            # Position cursor in nvim to match the input bar cursor position
            if editor.command_name == "nvim":
                if cursor_row > 0 or cursor_col > 0:
                    # nvim's cursor() is 1-indexed
                    cmd.extend(
                        [
                            "-c",
                            f"call cursor({cursor_row + 1}, {cursor_col + 1})",
                        ]
                    )
                elif cursor_position > 0:
                    cmd.extend(["-c", f"call cursor(1, {cursor_position + 1})"])
            cmd.append(temp_path)

            try:
                result = subprocess.run(cmd, check=False)
            except Exception:
                log.warning("Prompt editor failed; preserving draft", exc_info=True)
                result = None

            content = _read_editor_file(temp_path)
            if content is None:
                self._recover_prompt_editor_draft(temp_path, None)
                return None
            if result is None or result.returncode != 0:
                if content != initial_content:
                    self._recover_prompt_editor_draft(temp_path, content)
                else:
                    _unlink_editor_file(temp_path)
                return None

            _unlink_editor_file(temp_path)
            content = content.strip()
            return content if content else None

        # Recovery is deliberately local to this editor path. It never submits
        # the recovered prompt or changes the mounted prompt bar.

        self._prompt_editor_suspended = True
        try:
            with self.suspend():  # type: ignore[attr-defined]
                return run_editor()
        finally:
            self._prompt_editor_suspended = False

    def _open_workflow_yaml_editor(self) -> tuple[str, str] | None:
        """Suspend TUI and open editor for ad-hoc workflow YAML.

        Creates a YAML template, opens it in the user's editor, then saves the
        result to ~/sase/macros/ for execution.

        Returns:
            A (workflow_name, file_path) tuple, or None if cancelled/invalid.
        """
        import subprocess
        import tempfile

        import yaml  # type: ignore[import-untyped]
        from sase.core.time import generate_timestamp
        from sase.macro.loader import get_sase_package_macros_dir

        timestamp = generate_timestamp()
        default_name = f"adhoc_{timestamp}"
        schema_path = get_sase_package_macros_dir() / "workflow.schema.json"
        template = (
            "# yaml-language-server: $schema=" + str(schema_path) + "\n"
            "\n"
            "steps:\n"
            "  - name: main\n"
            "    prompt: |\n"
            "      <your prompt here>\n"
        )

        def run_editor() -> tuple[str, str] | None:
            from sase.core.paths import get_sase_managed_tmpdir

            fd, temp_path = tempfile.mkstemp(
                suffix=".yml",
                prefix="sase_ace_workflow_",
                dir=get_sase_managed_tmpdir("editors"),
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(template)

            editor = resolve_editor()
            try:
                result = subprocess.run([*editor.argv, temp_path], check=False)
            except Exception:
                log.warning("Workflow editor failed; preserving draft", exc_info=True)
                result = None

            content = _read_editor_file(temp_path)
            if content is None:
                self.notify(  # type: ignore[attr-defined]
                    f"Workflow draft could not be read; recovery file kept at {temp_path}",
                    severity="warning",
                )
                return None
            if result is None or result.returncode != 0:
                if content != template:
                    self.notify(  # type: ignore[attr-defined]
                        f"Workflow draft kept at {temp_path}",
                        severity="warning",
                    )
                else:
                    _unlink_editor_file(temp_path)
                return None

            _unlink_editor_file(temp_path)

            stripped = content.strip()
            if not stripped:
                return None

            # Parse YAML to extract workflow name
            try:
                data = yaml.safe_load(content)
            except yaml.YAMLError:
                return None

            if not isinstance(data, dict):
                return None

            workflow_name = default_name

            # Save to the canonical home macro directory.
            from sase.content_layout import resolve_home_layout

            macros_dir = str(resolve_home_layout().macros.write_path)
            os.makedirs(macros_dir, exist_ok=True)

            dest_path = os.path.join(macros_dir, f"{workflow_name}.yml")
            if os.path.exists(dest_path):
                # Append timestamp to avoid collision
                dest_path = os.path.join(macros_dir, f"{workflow_name}_{timestamp}.yml")

            with open(dest_path, "w", encoding="utf-8") as f:
                f.write(content)

            return (workflow_name, dest_path)

        with self.suspend():  # type: ignore[attr-defined]
            return run_editor()

    def _recover_prompt_editor_draft(self, temp_path: str, content: str | None) -> None:
        """Stash a changed prompt when possible and always retain its file."""
        if content is None:
            self.notify(  # type: ignore[attr-defined]
                f"Prompt draft could not be read; recovery file kept at {temp_path}",
                severity="warning",
            )
            return

        from datetime import datetime
        from uuid import uuid4

        from sase.core.paths import prompt_stash_path
        from sase.core.prompt_stash_facade import (
            PromptStashEntryWire,
            append_prompt_stash,
        )
        from sase.core.time import get_timezone

        entry_id = str(uuid4())
        prompt_context = getattr(self, "_prompt_context", None)
        entry = PromptStashEntryWire(
            id=entry_id,
            created_at=datetime.now(get_timezone()).isoformat(),
            text=content.strip(),
            project=getattr(prompt_context, "project_name", None),
            source="editor_recovered",
            pane_index=0,
        )
        try:
            append_prompt_stash(prompt_stash_path(), entry)
        except Exception:
            log.warning("Failed to stash recovered prompt editor draft", exc_info=True)
            self.notify(  # type: ignore[attr-defined]
                f"Prompt draft could not be stashed; recovery file kept at {temp_path}",
                severity="warning",
            )
            return

        self.notify(  # type: ignore[attr-defined]
            f"Recovered prompt stashed as {entry_id}; editor file kept at {temp_path}",
            severity="warning",
        )
