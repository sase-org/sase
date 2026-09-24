"""App-held Command Line session state and transcript blocks.

The session outlives the panel screen: hiding the panel keeps every block,
the unsent draft, the cwd pin, and the history cursor, so reopening with
``:`` re-mounts instantly with no disk I/O.
"""

from __future__ import annotations

import shlex
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

#: Maximum transcript blocks kept per app session.
COMMAND_LINE_MAX_BLOCKS = 200

BlockStatus = Literal[
    "submitting",
    "running",
    "success",
    "error",
    "submit_failed",
    "denied",
    "foreground",
    "builtin",
]


@dataclass
class CommandLineBlock:
    """One transcript block: a submitted command plus its streamed output."""

    block_id: str
    line: str
    status: BlockStatus = "submitting"
    proc_id: str | None = None
    placeholder_id: str | None = None
    exit_code: int | None = None
    started_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    elapsed: float | None = None
    tail_text: str = ""
    expanded: bool = False
    unseen: bool = False
    error: str | None = None
    pruned: bool = False
    #: True for blocks rebuilt from the proc store after a TUI restart.
    restored: bool = False
    #: True once this block's lazy tail has been read from the proc log.
    tail_loaded: bool = False
    #: Bytes the log rotation dropped underneath this block's cursor.
    lost_bytes: int = 0
    #: True when the command asks to confirm, ``-y/--yes`` was absent, and
    #: the proc failed: the block renders ``⊘ declined`` with an ``R``
    #: rerun-with-``-y`` hint (run-policies phase).
    declined: bool = False
    #: Resolver's ``confirms`` flag captured at submit time (declined logic).
    confirms: bool = False
    #: Resolver's ``confirm_flag_present`` captured at submit time.
    confirm_flag_present: bool = False

    @property
    def running(self) -> bool:
        """Return True while the block's proc is still streaming."""
        return self.status in ("submitting", "running")

    def elapsed_seconds(self, *, now: float | None = None) -> float:
        """Return seconds since submission (or until finish)."""
        end = (
            self.finished_at
            if self.finished_at is not None
            else (now if now is not None else time.monotonic())
        )
        return max(0.0, end - self.started_at)


@dataclass
class CommandLineSession:
    """App-held Command Line state: blocks, draft, cwd pin, history cursor."""

    blocks: list[CommandLineBlock] = field(default_factory=list)
    draft: str = ""
    draft_cursor: int = 0
    cwd_pin: str | None = None
    history_cursor: int | None = None
    restored: bool = False
    full_height: bool = False
    last_submit_at: float = 0.0
    last_submit_line: str = ""
    #: Block id with the NORMAL-mode selection bar; None means INSERT mode.
    selected_block_id: str | None = None
    #: Proc id a Procs-pane Enter jump wants selected; consumed on mount.
    focus_block_proc_id: str | None = None

    def add_block(self, line: str) -> CommandLineBlock:
        """Append a block and enforce the transcript cap."""
        block = CommandLineBlock(block_id=f"cmdline-{uuid.uuid4().hex}", line=line)
        self.blocks.append(block)
        while len(self.blocks) > COMMAND_LINE_MAX_BLOCKS:
            self.blocks.pop(0)
        return block

    def block_for_proc(self, proc_id: str) -> CommandLineBlock | None:
        """Return the block tracking *proc_id*, if any."""
        for block in self.blocks:
            if block.proc_id == proc_id:
                return block
        return None

    def block_by_id(self, block_id: str) -> CommandLineBlock | None:
        """Return the block with *block_id*, if any."""
        for block in self.blocks:
            if block.block_id == block_id:
                return block
        return None

    def running_blocks(self) -> list[CommandLineBlock]:
        """Return blocks that are still streaming."""
        return [block for block in self.blocks if block.running]

    def clear_transcript(self) -> None:
        """Drop finished blocks; running procs are untouched."""
        self.blocks = [block for block in self.blocks if block.running]
        if (
            self.selected_block_id is not None
            and self.block_by_id(self.selected_block_id) is None
        ):
            self.selected_block_id = None

    def selected_block(self) -> CommandLineBlock | None:
        """Return the NORMAL-mode selected block, if it still exists."""
        if self.selected_block_id is None:
            return None
        return self.block_by_id(self.selected_block_id)

    def select_block(self, block_id: str | None) -> CommandLineBlock | None:
        """Select *block_id* (viewing clears its unseen dot); None deselects."""
        self.selected_block_id = block_id
        if block_id is None:
            return None
        block = self.block_by_id(block_id)
        if block is None:
            self.selected_block_id = None
            return None
        block.unseen = False
        return block

    def move_selection(self, delta: int) -> CommandLineBlock | None:
        """Move the selection by *delta*, entering the transcript when empty."""
        if not self.blocks:
            return self.select_block(None)
        selected = self.selected_block()
        if selected is None:
            return self.select_block(self.blocks[-1].block_id)
        index = self.blocks.index(selected)
        index = max(0, min(len(self.blocks) - 1, index + delta))
        return self.select_block(self.blocks[index].block_id)

    def select_first(self) -> CommandLineBlock | None:
        """Jump the selection to the first block."""
        if not self.blocks:
            return self.select_block(None)
        return self.select_block(self.blocks[0].block_id)

    def select_last(self) -> CommandLineBlock | None:
        """Jump the selection to the last block."""
        if not self.blocks:
            return self.select_block(None)
        return self.select_block(self.blocks[-1].block_id)

    def remove_block(self, block_id: str) -> CommandLineBlock | None:
        """Remove a block from the transcript; the proc record is untouched."""
        block = self.block_by_id(block_id)
        if block is None:
            return None
        index = self.blocks.index(block)
        self.blocks.pop(index)
        if self.selected_block_id == block_id:
            if self.blocks:
                fallback = self.blocks[min(index, len(self.blocks) - 1)]
                self.select_block(fallback.block_id)
            else:
                self.selected_block_id = None
        return block

    def first_restored_index(self) -> int | None:
        """Return the index of the first restored block, if any."""
        for index, block in enumerate(self.blocks):
            if block.restored:
                return index
        return None


def command_line_session_for(app: Any) -> CommandLineSession:
    """Return the app-held session, creating it on first use."""
    session = getattr(app, "_command_line_session", None)
    if not isinstance(session, CommandLineSession):
        session = CommandLineSession()
        app._command_line_session = session
    return session


def tokenize_command_line(line: str) -> list[str] | None:
    """Tokenize a panel line into ``sase`` argv tokens.

    A leading ``sase `` the user typed or pasted is stripped at once; the
    ``sase`` prefix is implicit. Returns ``None`` for blank lines and
    unparseable (unterminated-quote) input.
    """
    text = line.strip()
    if not text:
        return None
    if text == "sase" or text.startswith("sase "):
        text = text[4:].strip()
        if not text:
            return None
    try:
        tokens = shlex.split(text, posix=True)
    except ValueError:
        return None
    return tokens or None


def strip_implicit_prefix(line: str) -> str:
    """Strip one leading ``sase `` prefix the user typed or pasted."""
    text = line.strip()
    if text == "sase":
        return ""
    if text.startswith("sase "):
        return text[5:].lstrip()
    return line


__all__ = [
    "COMMAND_LINE_MAX_BLOCKS",
    "BlockStatus",
    "CommandLineBlock",
    "CommandLineSession",
    "command_line_session_for",
    "strip_implicit_prefix",
    "tokenize_command_line",
]
