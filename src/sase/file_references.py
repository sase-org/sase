"""File reference processing for prompts."""

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from sase.markdown_literals import (
    EmphasisSentinels,
    protect_emphasis_literals,
    protect_intraword_underscores,
    restore_emphasis_literals,
    restore_intraword_underscores,
)
from sase.markdown_width import prettier_markdown_argv
from sase.output import (
    print_file_operation,
    print_status,
)

# Pattern to match '@' followed by a file path
# This captures paths like @/path/to/file.txt or @path/to/file
# We look for @ followed by non-whitespace characters that look like file paths
# Only match @ that is:
#   - At the start of the string (^)
#   - At the start of a line (after \n)
#   - After a space or whitespace character
#   - After a quote character (" or ')
# This prevents matching things like "foo@bar" or URLs with @ in them
# Note: parsing further filters tokens that are not file-shaped — URLs (http*),
# bare identifiers with no `/` and no `.` (e.g. @IgnoreForDiff), and
# TLD-suffixed domain names (e.g. @google.com) — leaving them in the prompt
# verbatim rather than reporting them as missing files.
_FILE_REF_PATTERN = r"(?:^|(?<=\s)|(?<=[\"']))@((?:[^\s,;:()[\]{}\"'`])+)"

# Common TLDs used to skip domain-like patterns
_COMMON_TLDS = (
    ".com",
    ".org",
    ".net",
    ".io",
    ".edu",
    ".gov",
    ".co",
    ".dev",
    ".app",
)


@dataclass
class _ParsedFileRefs:
    """Holds categorized file references from parsing."""

    absolute_paths: list[tuple[str, str]] = field(default_factory=list)
    relative_paths: list[str] = field(default_factory=list)
    parent_dir_paths: list[str] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)
    seen_paths: dict[str, int] = field(default_factory=dict)

    @property
    def duplicate_paths(self) -> list[str]:
        """Return paths that appear more than once."""
        return [path for path, count in self.seen_paths.items() if count > 1]


def _parse_file_refs(prompt: str) -> _ParsedFileRefs:
    """
    Parse @file references in the prompt and categorize them.

    Args:
        prompt: The prompt text to parse

    Returns:
        Categorized file references
    """
    result = _ParsedFileRefs()

    # Find all matches (MULTILINE so ^ matches start of each line)
    matches = re.findall(_FILE_REF_PATTERN, prompt, re.MULTILINE)

    if not matches:
        return result

    for file_path in matches:
        # Clean up the path (remove trailing punctuation)
        file_path = file_path.rstrip(".,;:!?)")

        # Skip if it looks like a URL
        if file_path.startswith("http"):
            continue

        # Skip bare-word tokens with no path separator and no extension —
        # these are almost always literal markers (e.g. @IgnoreForDiff), not files.
        if "/" not in file_path and "." not in file_path:
            continue

        # Skip if it looks like a domain name (e.g., @google.com at start of line)
        # Domain names end with common TLDs and don't contain path separators
        if "/" not in file_path and any(
            file_path.endswith(tld) for tld in _COMMON_TLDS
        ):
            continue

        # Track this file path for duplicate detection
        result.seen_paths[file_path] = result.seen_paths.get(file_path, 0) + 1

        # Expand tilde (~) to home directory
        expanded_path = os.path.expanduser(file_path)

        # Check if the file path is absolute (after tilde expansion)
        if os.path.isabs(expanded_path):
            # Validate existence using expanded path
            if not os.path.exists(expanded_path):
                if file_path not in result.missing_files:
                    result.missing_files.append(file_path)
            else:
                # Store tuple of (original_path, expanded_path) for later processing
                if not any(orig == file_path for orig, _ in result.absolute_paths):
                    result.absolute_paths.append((file_path, expanded_path))
            continue

        # Check if the file path starts with '..' (tries to escape CWD)
        if file_path.startswith(".."):
            if file_path not in result.parent_dir_paths:
                result.parent_dir_paths.append(file_path)
            continue

        # Check if the file exists (relative path)
        if not os.path.exists(file_path):
            if file_path not in result.missing_files:
                result.missing_files.append(file_path)
        elif file_path not in result.relative_paths:
            result.relative_paths.append(file_path)

    return result


def _print_validation_errors(parsed: _ParsedFileRefs) -> bool:
    """
    Print validation errors and return True if any errors were found.

    Args:
        parsed: The parsed file references

    Returns:
        True if validation errors were found, False otherwise
    """
    has_errors = False

    if parsed.parent_dir_paths:
        has_errors = True
        print(
            "\n❌ ERROR: The following file(s) use parent directory paths ('..' prefix) in '@' references:"
        )
        for file_path in parsed.parent_dir_paths:
            print(f"  - @{file_path}")
        print("\n⚠️ '@' file references MUST NOT start with '..' to escape the CWD.")
        print(
            "⚠️ This ensures agents can only access files within the project directory."
        )
        print("⚠️ File validation failed. Terminating workflow to prevent errors.\n")

    if parsed.missing_files:
        has_errors = True
        print(
            "\n❌ ERROR: The following file(s) referenced in the prompt do not exist:"
        )
        for file_path in parsed.missing_files:
            print(f"  - @{file_path}")
        print("\n⚠️ File validation failed. Terminating workflow to prevent errors.\n")

    if parsed.duplicate_paths:
        has_errors = True
        print(
            "\n❌ ERROR: The following file(s) have duplicate '@' references in the prompt:"
        )
        for file_path in parsed.duplicate_paths:
            count = parsed.seen_paths[file_path]
            print(f"  - @{file_path} (appears {count} times)")
        print("\n⚠️ Each file should be referenced with '@' only ONCE in the prompt.")
        print("⚠️ Duplicate references waste tokens and can confuse the AI agent.")
        print("⚠️ File validation failed. Terminating workflow to prevent errors.\n")

    return has_errors


def validate_file_references(prompt: str) -> None:
    """
    Validate @file references in the prompt without modifying it.

    Checks that:
    1. All referenced files exist
    2. No paths use '..' to escape the current working directory
    3. No duplicate file references

    Note: Unlike process_file_references(), this does NOT check for reserved
    context directory usage or copy any files.

    Args:
        prompt: The prompt text to validate

    Raises:
        SystemExit: If any validation error is found
    """
    parsed = _parse_file_refs(prompt)
    if _print_validation_errors(parsed):
        sys.exit(1)


def process_file_references(
    prompt: str,
    *,
    is_home_mode: bool = False,
    staged_file_paths: set[str] | None = None,
) -> str:
    """
    Process file paths prefixed with '@' in the prompt.

    For absolute paths (when is_home_mode=False):
    - Home-directory files (~/ paths): copy to
      .sase/artifacts/home/<path_relative_to_home>/
    - Non-home absolute files: leave the absolute path in the prompt unchanged

    For absolute paths (when is_home_mode=True):
    - Just expand ~ to the full home directory path (no copying)

    For relative paths: validate they exist and don't escape CWD

    This function extracts all file paths from the prompt that are prefixed
    with '@' and verifies that:
    1. Home-dir absolute paths are copied to .sase/artifacts/home/ (or just
       expanded in home mode)
    2. Non-home absolute paths are left unchanged in the prompt
    3. Relative paths do not start with '..' (to prevent escaping CWD)
    4. All files exist
    5. There are no duplicate file path references

    If any file starts with '..', does not exist, or is duplicated,
    it prints an error message and terminates the script.

    Args:
        prompt: The prompt text to process
        is_home_mode: If True, skip copying files and just expand tilde paths
        staged_file_paths: Resolved paths already staged by artifact-reference
            expansion, used to skip restaging when an explicit custom
            path-bound provider still emits an ``@path`` token

    Returns:
        The modified prompt with home-dir paths replaced by relative paths to
        .sase/artifacts/home/ (or expanded paths in home mode)

    Raises:
        SystemExit: If any referenced file starts with '..', does not exist, or is duplicated
    """
    parsed = _parse_file_refs(prompt)

    if _print_validation_errors(parsed):
        sys.exit(1)

    # In home mode, just expand tilde paths without copying
    if is_home_mode:
        modified_prompt = prompt
        for original_path, expanded_path in parsed.absolute_paths:
            # Only replace if the path differs (i.e., had a tilde to expand)
            if original_path != expanded_path:
                modified_prompt = modified_prompt.replace(
                    f"@{original_path}", f"@{expanded_path}"
                )
        return modified_prompt

    # Split absolute paths into home-dir vs non-home
    home_dir = os.path.expanduser("~")
    home_paths: list[tuple[str, str]] = []

    for original_path, expanded_path in parsed.absolute_paths:
        if expanded_path.startswith(home_dir + "/") or expanded_path == home_dir:
            home_paths.append((original_path, expanded_path))

    # Copy home-directory files to .sase/artifacts/home/<relative_path>
    if home_paths:
        file_count = len(home_paths)
        file_word = "file" if file_count == 1 else "files"
        print_status(
            "Processing "
            f"{file_count} home-dir {file_word} - copying to "
            ".sase/artifacts/home/",
            "info",
        )

    replacements: dict[str, str] = {}

    for original_path, expanded_path in home_paths:
        rel_path = os.path.relpath(expanded_path, home_dir)
        dest_path = os.path.join(".sase", "artifacts", "home", rel_path)

        # Create parent directories as needed
        Path(dest_path).parent.mkdir(parents=True, exist_ok=True)

        try:
            shutil.copy2(expanded_path, dest_path)
            replacements[original_path] = dest_path
            basename = os.path.basename(expanded_path)
            print_file_operation(f"Copied for agent: {basename}", dest_path, True)
        except Exception as e:
            print_status(f"Failed to copy {expanded_path} to {dest_path}: {e}", "error")

    # Apply replacements to prompt
    modified_prompt = prompt
    for old_path, new_path in replacements.items():
        modified_prompt = modified_prompt.replace(f"@{old_path}", f"@{new_path}")

    # Notify user that prompt was modified
    replacement_count = len(replacements)
    if replacement_count > 0:
        path_word = "path" if replacement_count == 1 else "paths"
        print_status(
            f"Prompt modified: {replacement_count} absolute {path_word} replaced with relative paths",
            "success",
        )

    _stage_file_references(
        parsed,
        replacements,
        staged_file_paths=staged_file_paths or set(),
    )

    return modified_prompt


def _stage_file_references(
    parsed: _ParsedFileRefs,
    replacements: dict[str, str],
    *,
    staged_file_paths: set[str],
) -> None:
    """Best-effort staging for every resolved plain ``@path`` reference."""

    from sase.core.prompt_artifact_staging import stage_prompt_artifact

    for original_path, expanded_path in parsed.absolute_paths:
        if _normalized_staging_path(expanded_path) in staged_file_paths:
            continue
        rewritten_path = replacements.get(original_path, original_path)
        stage_prompt_artifact(
            raw_ref=f"@{original_path}",
            expanded_ref=f"@{rewritten_path}",
            resolved_path=expanded_path,
            ref_kind="file",
            label=Path(expanded_path).name,
        )
    for relative_path in parsed.relative_paths:
        if _normalized_staging_path(relative_path) in staged_file_paths:
            continue
        stage_prompt_artifact(
            raw_ref=f"@{relative_path}",
            expanded_ref=f"@{relative_path}",
            resolved_path=relative_path,
            ref_kind="file",
            label=Path(relative_path).name,
        )


def _normalized_staging_path(path: Path | str) -> str:
    return str(Path(path).expanduser().resolve(strict=False))


# --- Cached shell execution for the source-aware command boundary ---
#
# Command planning lives in the sase_core policy (see
# sase.macro.cmdsub_source); this module only shells out through the cache.

# Command cache for command execution to avoid duplicate runs.
_cmd_cache: dict[str, tuple[str | None, bool]] = {}


def execute_cmd_cached(cmd: str) -> tuple[str | None, bool]:
    """
    Execute a command with caching to avoid duplicate runs.

    Public because the source-aware command-substitution boundary in
    :mod:`sase.macro.cmdsub_source` executes planned commands through it;
    the cache itself stays module-private.


    Args:
        cmd: The shell command to execute

    Returns:
        Tuple of (output, success) where output is stdout and success is True if exit code was 0
    """
    if cmd in _cmd_cache:
        return _cmd_cache[cmd]

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            check=False,
        )
        output = result.stdout
        success = result.returncode == 0
        _cmd_cache[cmd] = (output, success)
        return output, success
    except Exception:
        _cmd_cache[cmd] = (None, False)
        return None, False


def format_with_prettier(text: str, *, print_width: int | None = None) -> str:
    """Format text with prettier if available.

    Uses the shared ``prettier_markdown_argv()`` policy to format the text as
    markdown with always-on prose wrapping, wrapping prose at *print_width*
    columns. Falls back to returning the original text if prettier is not
    installed, returns an error, times out, or cannot produce usable output.

    Args:
        text: The markdown text to format.
        print_width: The column width to wrap prose at. ``None`` (the default)
            resolves the configured width, which is what every caller (plans,
            SDD files, skills, notifications, agent prompts) uses today. It is
            passed straight through to ``prettier_markdown_argv()`` so there is
            exactly one resolution point.
    """
    original = text
    if shutil.which("prettier") is None:
        return original

    protected, sentinel = protect_intraword_underscores(original)
    try:
        result = subprocess.run(
            prettier_markdown_argv(print_width=print_width),
            input=protected,
            capture_output=True,
            text=True,
            check=True,
            # A hung prettier (e.g. a package-manager shim waiting on the
            # network) must not hang callers like `sase doctor`.
            timeout=10.0,
        )
        # Unescape underscores that prettier escaped for markdown safety.
        # This preserves literal underscores in filenames and identifiers.
        # Loop because prettier can double-escape (\_  → \\_), and a single
        # replace only peels one layer.
        formatted = result.stdout
        while r"\_" in formatted:
            formatted = formatted.replace(r"\_", "_")
        return restore_intraword_underscores(formatted, sentinel)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return original


def format_markdown_files_with_prettier(
    paths: Iterable[Path],
    *,
    print_width: int | None = None,
) -> bool:
    """Format many Markdown files in one prettier process.

    Returns whether prettier ran successfully. Missing, failed, or timed-out
    prettier leaves the supplied files as-is.
    """

    selected = tuple(dict.fromkeys(Path(path) for path in paths))
    if not selected:
        return True
    if shutil.which("prettier") is None:
        return False

    originals: list[tuple[Path, str, str]] = []
    for path in selected:
        original = path.read_text(encoding="utf-8")
        protected, sentinel = protect_intraword_underscores(original)
        originals.append((path, original, sentinel))
        if protected != original:
            path.write_text(protected, encoding="utf-8")
    try:
        subprocess.run(
            [
                *prettier_markdown_argv(print_width=print_width),
                "--write",
                *(str(path) for path in selected),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=max(10.0, min(300.0, 10.0 + len(selected) * 0.25)),
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        for path, original, _sentinel in originals:
            path.write_text(original, encoding="utf-8")
        return False

    for path, _original, sentinel in originals:
        text = path.read_text(encoding="utf-8")
        restored = restore_intraword_underscores(
            _unescape_prettier_underscores(text), sentinel
        )
        if restored != text:
            path.write_text(restored, encoding="utf-8")
    return True


def _unescape_prettier_underscores(text: str) -> str:
    while r"\_" in text:
        text = text.replace(r"\_", "_")
    return text


def format_agent_prompt_markdown(text: str) -> str:
    """Format editable/launch-time agent prompt Markdown canonically.

    Agent-prompt formatting is prettier reflow plus block normalization, but
    inline ``_`` / ``*`` characters are preserved literally. Launch-time
    preprocessing, the editor ``gf`` action, and the published prompt document
    still share this one helper. Plain ``format_with_prettier`` keeps raw
    prettier parity except for intraword underscores, which are protected
    because raw prettier corrupts them.
    """
    protected: str
    sentinels: EmphasisSentinels
    protected, sentinels = protect_emphasis_literals(text)
    return restore_emphasis_literals(format_with_prettier(protected), sentinels)


def strip_html_comments(text: str) -> str:
    """Strip HTML/markdown comments from text while preserving code blocks.

    Removes all HTML comments (<!-- ... -->) from the text, including
    multi-line comments. Comments inside fenced code blocks (```...```)
    are preserved.

    Args:
        text: The text to process

    Returns:
        The text with HTML comments removed
    """
    if "<!--" not in text:
        return text

    # Protect fenced code blocks from comment stripping
    code_blocks: list[str] = []
    placeholder_template = "\x00CODE_BLOCK_{}\x00"

    def _save_code_block(match: re.Match[str]) -> str:
        code_blocks.append(match.group(0))
        return placeholder_template.format(len(code_blocks) - 1)

    # Pattern for fenced code blocks: ``` optionally followed by language, then content, then ```
    code_block_pattern = r"```[^\n]*\n[\s\S]*?```"
    protected_text = re.sub(code_block_pattern, _save_code_block, text)

    # Strip HTML comments
    comment_pattern = r"<!--[\s\S]*?-->"
    result = re.sub(comment_pattern, "", protected_text)

    # Restore code blocks
    for i, block in enumerate(code_blocks):
        result = result.replace(placeholder_template.format(i), block)

    return result
