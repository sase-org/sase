"""Editor utilities for prompt editing."""

import os
import subprocess
import tempfile

from sase.editor_resolver import resolve_editor


def _get_editor_argv() -> tuple[str, ...]:
    """Return the editor command as argv."""
    return resolve_editor().argv


def open_editor_for_prompt() -> str | None:
    """Open the user's editor with a blank file for writing a prompt.

    Returns:
        The prompt content, or None if the user didn't write anything
        or the editor failed.
    """
    from sase.core.paths import get_sase_managed_tmpdir

    fd, temp_path = tempfile.mkstemp(
        suffix=".md",
        prefix="sase_prompt_",
        dir=get_sase_managed_tmpdir("editors"),
    )
    os.close(fd)

    editor_argv = _get_editor_argv()

    try:
        result = subprocess.run([*editor_argv, temp_path], check=False)
        if result.returncode != 0:
            print("Editor exited with non-zero status.")
            os.unlink(temp_path)
            return None

        with open(temp_path, encoding="utf-8") as f:
            content = f.read().strip()

        os.unlink(temp_path)

        if not content:
            return None

        return content

    except Exception as e:
        print(f"Failed to open editor: {e}")
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        return None


def _open_editor_with_content(initial_content: str) -> str | None:
    """Open the user's editor with pre-filled content for editing.

    Args:
        initial_content: The content to pre-fill in the editor.

    Returns:
        The edited content, or None if the user left it empty or the editor failed.
    """
    from sase.core.paths import get_sase_managed_tmpdir

    fd, temp_path = tempfile.mkstemp(
        suffix=".md",
        prefix="sase_prompt_",
        dir=get_sase_managed_tmpdir("editors"),
    )

    editor_argv = _get_editor_argv()

    try:
        # Write initial content to temp file
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(initial_content)

        result = subprocess.run([*editor_argv, temp_path], check=False)
        if result.returncode != 0:
            print("Editor exited with non-zero status.")
            os.unlink(temp_path)
            return None

        with open(temp_path, encoding="utf-8") as f:
            content = f.read().strip()

        os.unlink(temp_path)

        if not content:
            return None

        return content

    except Exception as e:
        print(f"Failed to open editor: {e}")
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        return None


def edit_prompt_text(initial_content: str) -> str | None:
    """Open the editor pre-filled with *initial_content* and return the result.

    Returns the edited text, or ``None`` if the editor failed or the user left
    the buffer empty. Shared by ``sase prompt run --edit``/``edit``/``select``
    so editing a replayed prompt matches the ``sase run "."`` editor flow.
    """
    return _open_editor_with_content(initial_content)


def show_prompt_history_picker() -> str | None:
    """Show fzf picker for prompt history, open editor, return edited prompt.

    Returns:
        The edited prompt content, or None if cancelled or no history.
    """
    return _show_prompt_history_picker()


def _show_prompt_history_picker() -> str | None:
    """Show fzf picker for prompt history, open editor.

    Returns:
        The edited prompt content, or None if cancelled or no history.
    """
    from sase.history.prompt import get_prompts_for_fzf

    items = get_prompts_for_fzf()

    if not items:
        print("No prompt history found. Run 'sase run \"your prompt\"' first.")
        return None

    # Check if fzf is available
    fzf_check = subprocess.run(
        ["which", "fzf"], capture_output=True, text=True, check=False
    )
    if fzf_check.returncode != 0:
        print("Error: fzf is not installed. Please install fzf to use prompt history.")
        return None

    # Build display lines for fzf with a stable selection key. The preview
    # text is display-only and may be humanized, truncated, or duplicated.
    indexed_items = [
        (f"{index:04d}  {display}", entry)
        for index, (display, entry) in enumerate(items)
    ]
    entry_by_key = {line.split(maxsplit=1)[0]: entry for line, entry in indexed_items}
    display_lines = "\n".join(line for line, _ in indexed_items)

    cmd = [
        "fzf",
        "--prompt",
        "Select prompt> ",
        "--header",
        "Most recent prompts first",
    ]

    result = subprocess.run(
        cmd,
        input=display_lines,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        # User cancelled (Escape or Ctrl-C)
        return None

    selected_display = result.stdout.strip()
    if not selected_display:
        return None

    selected_key = selected_display.split(maxsplit=1)[0]
    selected_entry = entry_by_key.get(selected_key)
    if selected_entry is None:
        return None

    # Open editor with selected prompt pre-filled
    return _open_editor_with_content(selected_entry.text)
