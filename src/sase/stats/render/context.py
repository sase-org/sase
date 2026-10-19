"""Injectable clock, width, and host identity for Projects report renderers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sase.config import get_local_machine_name
from sase.core.time import get_timezone

_DEFAULT_MACHINE = "this machine"


@dataclass(frozen=True, slots=True)
class RenderContext:
    """Presentation knobs every Projects section renderer reads.

    Clock, zone, and hostname are injectable so width-pinned goldens stay
    host-independent. Color and Unicode follow the destination console.
    """

    width: int
    color: bool
    unicode: bool
    now: datetime
    timezone: ZoneInfo | Any
    machine: str

    @classmethod
    def from_console(
        cls,
        console: Any,
        *,
        now: datetime | None = None,
        machine: str | None = None,
    ) -> RenderContext:
        """Build a context from a Rich console, with optional pinned clock."""
        timezone = get_timezone()
        current = now if now is not None else datetime.now(timezone)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone)
        else:
            current = current.astimezone(timezone)
        encoding = (getattr(console, "encoding", None) or "utf-8").lower()
        ascii_only = bool(getattr(console.options, "legacy_windows", False))
        color_system = getattr(console, "color_system", None)
        no_color = bool(getattr(console, "no_color", False))
        return cls(
            width=int(console.size.width),
            color=color_system is not None and not no_color,
            unicode="utf" in encoding.replace("-", "") and not ascii_only,
            now=current,
            timezone=timezone,
            machine=machine or get_local_machine_name() or _DEFAULT_MACHINE,
        )

    @property
    def stacked(self) -> bool:
        return self.width < 60

    @property
    def show_detail_columns(self) -> bool:
        """FIRST/LAST COMMIT, DOC LINES, and EPIC/TALE drop at the 80-column layout."""
        return self.width >= 100
