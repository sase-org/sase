"""Rendering helpers that build Option rows for the agent list widget."""

from collections import OrderedDict
from datetime import datetime
from typing import Any

from rich.text import Text
from textual.widgets.option_list import Option
from sase.xprompt.workflow_output import get_substep_suffix

from ..models.agent import (
    Agent,
    AgentType,
    AttemptRecord,
    compute_row_runtime,
    format_compact_duration,
)
from ..models.agent_groups import (
    GroupingMode,
    GroupRow,
    banner_label,
    banner_summary_text,
    compute_banner_summary,
)
from ._agent_list_helpers import short_model_name, step_role_suffix
from ._agent_list_styling import (
    _AGENT_TYPE_COLORS,
    _APPROVE_ICON,
    _CHANGESPEC_BANNER_BAR_STYLE,
    _CHANGESPEC_BANNER_RULE_STYLE,
    _CHANGESPEC_BAR_GLYPH,
    _CHANGESPEC_RULE,
    _CHILD_INDENT,
    _HIDDEN_ICON,
    _NAME_ROOT_BANNER_BRANCH_STYLE,
    _NAME_ROOT_BANNER_LABEL_STYLE,
    _NAME_ROOT_BRANCH_GLYPH,
    _NAME_ROOT_RULE,
    _PROJECT_BANNER_BAR_STYLE,
    _PROJECT_BANNER_RULE_STYLE,
    _PROJECT_BAR_GLYPH,
    _PROJECT_RULE,
    _STATUS_BUCKET_GLYPHS,
    _STEP_TYPE_COLORS,
    _TIER_GUIDE_SEGMENT,
    _TIER_GUIDE_SEGMENT_WIDTH,
    _TYPE_GLYPHS,
)

# Timestamp half: muted lavender-steel.  No `dim` attribute so the color
# carries on its own; chosen to harmonize with WAITING amethyst (#AF87FF)
# and project-banner sky-blue (#5FAFFF) while staying clearly less
# saturated, so the timestamp reads as a "metadata column" rather than a
# status word.
_RUNTIME_TS_STYLE = "#8787AF"
# Date prefix half (e.g. "Apr 26 ", "Apr 26 '25"): same hue as the time
# half but dimmed so the date reads as context while the time stays the
# salient anchor when scanning rows.
_RUNTIME_DATE_STYLE = "dim #8787AF"
# Elapsed half: light neutral grey, bold to give the headline number
# ("how long?") a little more weight than the timestamp without using
# a saturated color.  Readable on dark and light themes alike.
_RUNTIME_ELAPSED_STYLE = "bold #BCBCBC"


_AGENT_CACHE_MAX = 512
_BANNER_CACHE_MAX = 128


def _render_tier_gutter(tier_styles: tuple[str, ...]) -> Text:
    """Build the leading tier-guide gutter for a row.

    Emits one ``│  `` segment per supplied style, in order from outermost
    (project / bucket) to innermost (ChangeSpec).  Returns an empty Text
    when *tier_styles* is empty so callers can prepend unconditionally.
    """
    gutter = Text()
    for style in tier_styles:
        gutter.append(_TIER_GUIDE_SEGMENT, style=style)
    return gutter


def _bounded_lru_get(cache: "OrderedDict[Any, Any]", key: Any) -> Any:
    """Move *key* to most-recent if present and return its value, else ``None``.

    LRU eviction happens in :func:`_bounded_lru_put`; ``get`` only touches
    ordering when the key already exists.
    """
    value = cache.get(key)
    if value is not None:
        cache.move_to_end(key)
    return value


def _bounded_lru_put(
    cache: "OrderedDict[Any, Any]", key: Any, value: Any, *, maxsize: int
) -> None:
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > maxsize:
        cache.popitem(last=False)


def _quantize_now(now: datetime | None) -> tuple[int, int, int, int, int, int] | None:
    """Quantize *now* to per-second precision so cache keys are hashable + stable.

    Returns ``None`` when *now* is ``None`` so cache entries built with the
    default clock don't collide with explicit-time renders.
    """
    if now is None:
        return None
    return (now.year, now.month, now.day, now.hour, now.minute, now.second)


def _runtime_signature(agent: Agent, now: datetime | None) -> tuple[Any, ...]:
    """Return a tuple of agent fields that drive the runtime suffix.

    ``RUNNING`` / ``WAITING`` / ``RETRYING`` agents have a status display
    that depends on time-of-day; their signature folds in the quantized
    *now* so a cache hit only happens within the same wall-clock second.
    Terminal agents have a stable signature regardless of *now*.
    """
    time_sensitive = agent.status in ("RUNNING", "WAITING", "RETRYING")
    return (
        agent.status,
        agent.start_time,
        getattr(agent, "wait_until", None),
        getattr(agent, "wait_duration", None),
        getattr(agent, "retry_next_at_epoch", None),
        agent.retry_count,
        agent.using_fallback,
        agent.fallback_model,
        _quantize_now(now) if time_sensitive else None,
    )


def _agent_render_key(
    agent: Agent,
    index: int,
    *,
    is_selected: bool,
    fold_annotation: str,
    is_expanded: bool,
    is_marked: bool,
    hint_char: str | None,
    now: datetime | None,
    tier_styles: tuple[str, ...] = (),
) -> tuple[Any, ...]:
    """Build the cache key for a single agent row.

    Captures every input that affects ``format_agent_option``'s output —
    if any of these values changes, the cached entry is no longer valid
    and the row must be re-rendered. The key is intentionally explicit
    (no ``vars(agent)``) so adding a new visible field is a deliberate
    edit here rather than a silent cache desync.
    """
    return (
        agent.identity,
        index,
        is_selected,
        fold_annotation,
        is_expanded,
        is_marked,
        hint_char,
        agent.approve,
        agent.tag,
        agent.agent_name,
        agent.hidden,
        agent.retry_attempt,
        agent.is_workflow_child,
        agent.appears_as_agent,
        agent.is_anonymous,
        agent.step_index,
        agent.total_steps,
        agent.parent_step_index,
        agent.parent_total_steps,
        agent.step_type,
        agent.embedded_workflow_name,
        agent.is_pre_prompt_step,
        agent.agent_type,
        agent.display_name,
        agent.cl_name,
        tier_styles,
        _runtime_signature(agent, now),
    )


def _build_runtime_suffix(agent: Agent, now: datetime | None = None) -> Text:
    """Return a Rich ``Text`` for the right-side runtime suffix (may be empty)."""
    ts_pair, elapsed = compute_row_runtime(agent, now=now)
    suffix = Text()
    if ts_pair is None and elapsed is None:
        return suffix
    if ts_pair is not None:
        date_part, time_part = ts_pair
        if date_part:
            suffix.append(date_part, style=_RUNTIME_DATE_STYLE)
        if time_part:
            suffix.append(time_part, style=_RUNTIME_TS_STYLE)
        suffix.append(" · ", style=_RUNTIME_TS_STYLE)
    if elapsed is not None:
        suffix.append(elapsed, style=_RUNTIME_ELAPSED_STYLE)
    return suffix


def _build_attempt_runtime_suffix(record: AttemptRecord) -> Text:
    """Return a Rich ``Text`` with the attempt's elapsed duration (may be empty)."""
    suffix = Text()
    duration_secs = record.end_epoch - record.start_epoch
    if duration_secs > 0:
        suffix.append(
            format_compact_duration(duration_secs), style=_RUNTIME_ELAPSED_STYLE
        )
    return suffix


def assemble_padded_option(
    left: Text,
    suffix: Text,
    *,
    width: int,
    option_id: str,
    disabled: bool = False,
) -> Option:
    """Combine ``left`` and ``suffix`` into a single Option, right-aligned.

    Pads with spaces so the suffix's right edge sits at ``width`` cells,
    falling back to a 2-cell gap when ``left + suffix`` already meets or
    exceeds ``width``.  Rows whose suffix is empty render with no padding
    at all (their column is just left content).
    """
    if suffix.cell_len == 0:
        return Option(left, id=option_id, disabled=disabled)
    pad_len = max(2, width - left.cell_len - suffix.cell_len)
    combined = Text()
    combined.append_text(left)
    combined.append(" " * pad_len)
    combined.append_text(suffix)
    return Option(combined, id=option_id, disabled=disabled)


def format_agent_option(
    agent: Agent,
    index: int,
    *,
    is_selected: bool,
    fold_annotation: str = "",
    is_expanded: bool = False,
    is_marked: bool = False,
    hint_char: str | None = None,
    now: datetime | None = None,
    tier_styles: tuple[str, ...] = (),
) -> tuple[Text, Text, str]:
    """Build ``(left_text, suffix_text, option_id)`` parts for an agent row."""
    text = _render_tier_gutter(tier_styles)
    if hint_char is not None:
        text.append(f"[{hint_char}] ", style="bold #FFFF00")

    if is_marked:
        text.append("[✓] ", style="bold #00D700")

    # Approve icon for autonomous agents
    if agent.approve:
        text.append(f"{_APPROVE_ICON} ", style="bold #00FFFF")

    # Indentation for retry-chain attempts: render under the chain
    # root so the user sees the lineage at a glance.  retry_attempt
    # tracks chain depth (1 = first retry, 2 = retry-of-retry, …).
    if agent.retry_attempt > 0 and not agent.is_workflow_child:
        indent = "  " * agent.retry_attempt + "↳ "
        text.append(indent, style="dim #808080")

    # Indentation for workflow child agents
    if agent.is_workflow_child:
        text.append(_CHILD_INDENT, style="dim #808080")
        if agent.step_index is not None:
            if (
                agent.parent_step_index is not None
                and agent.parent_total_steps is not None
            ):
                # Embedded step: format as "1a/7"
                parent_num = agent.parent_step_index + 1
                substep = get_substep_suffix(agent.step_index)
                text.append(
                    f"{parent_num}{substep}/{agent.parent_total_steps} ",
                    style="dim #AAAAAA",
                )
            elif agent.total_steps is not None:
                # Regular step: format as "1/3" or "1/3.plan"
                step_num = agent.step_index + 1
                role = step_role_suffix(agent)
                text.append(
                    f"{step_num}/{agent.total_steps}{role} ", style="dim #AAAAAA"
                )

    # Hidden icon for agents that are normally hidden
    if agent.hidden:
        text.append(f"{_HIDDEN_ICON} ", style="bold #FF5F87")

    # Spawn-on-retry: prefix retry attempts with a small ↻N badge so
    # the user can pattern-match the chain depth without opening the
    # detail panel.  retry_attempt == 0 means "not a retry" and is not
    # rendered.
    if agent.retry_attempt > 0:
        badge_color = "#FFAF00"  # warm yellow
        text.append(f"↻{agent.retry_attempt} ", style=f"bold {badge_color}")

    # Agent type indicator with color
    dt = agent.get_display_type(is_expanded=is_expanded)

    # Color: RUNNING blue for appears_as_agent, per-step-type for workflow children
    is_appears_as_agent = agent.appears_as_agent and not (
        agent.is_anonymous and is_expanded
    )
    if is_appears_as_agent:
        color = _AGENT_TYPE_COLORS[AgentType.RUNNING]
    elif agent.is_workflow_child and agent.step_type in _STEP_TYPE_COLORS:
        color = _STEP_TYPE_COLORS[agent.step_type]
    else:
        color = _AGENT_TYPE_COLORS.get(agent.agent_type, "#FFFFFF")

    # Compact type prefix: ``agent``-typed rows omit the bracket entirely
    # (their color already encodes the type and the workflow-child indent
    # already marks tree depth).  Other top-level types render as a
    # single-glyph badge; unknown types fall back to ``[X] `` for debug
    # readability.
    if not (is_appears_as_agent or agent.is_workflow_child):
        type_glyph = _TYPE_GLYPHS.get(dt)
        if type_glyph is not None:
            text.append(f"{type_glyph} ", style=f"bold {color}")
        else:
            text.append(f"[{dt}] ", style=f"bold {color}")

    # Agent display name (workflow name for top-level workflows, CL name otherwise)
    name_style = "bold #00D7AF" if is_selected else "#00D7AF"
    text.append(agent.display_name, style=name_style)

    # Status (wrapped in parentheses, parens are dim)
    text.append(" (", style="dim")
    if agent.status == "RUNNING":
        text.append(agent.status, style="bold #FFD700")  # Gold
    elif agent.status in ("DONE", "PLAN DONE"):
        text.append(agent.status, style="bold #5FD75F")  # Green
    elif agent.status == "EPIC CREATED":
        text.append(agent.status, style="bold #5FD7AF")  # Sea-green
    elif agent.status == "FAILED":
        text.append(agent.status, style="bold #FF5F5F")  # Red
    elif agent.status == "FAILED (RETRIED)":
        # Spawn-on-retry: dim red + warm yellow ↻ glyph indicates a
        # terminal failure that handed off to a downstream retry, as
        # opposed to a dead-end failure with no recovery attempt.
        text.append("FAILED ", style="dim #FF5F5F")
        text.append("↻", style="bold #FFAF00")
        text.append(" (RETRIED)", style="dim #FF5F5F")
    elif agent.status == "PLANNING":
        text.append(agent.status, style="bold #FF87AF")  # Pink
    elif agent.status == "PLAN APPROVED":
        text.append(agent.status, style="bold #00D7AF")  # Green-blue (teal)
    elif agent.status == "WAITING":
        text.append(agent.status, style="bold #AF87FF")  # Amethyst
        if agent.wait_until:
            from datetime import datetime as _dt

            from sase.ace.tui.models.agent import format_wait_until

            target_label = format_wait_until(agent.wait_until)
            target = _dt.fromisoformat(agent.wait_until)
            remaining = (target - _dt.now()).total_seconds()
            if remaining > 0:
                text.append(
                    f" (until {target_label}, {format_compact_duration(remaining)})",
                    style="#AF87FF",
                )
            else:
                text.append(f" (until {target_label})", style="#AF87FF")
        elif agent.wait_duration and agent.start_time:
            from datetime import datetime, timedelta

            target = agent.start_time + timedelta(seconds=agent.wait_duration)
            remaining = (target - datetime.now()).total_seconds()
            if remaining > 0:
                text.append(
                    f" ({format_compact_duration(remaining)})",
                    style="#AF87FF",
                )
    elif agent.status == "QUESTION":
        text.append(agent.status, style="bold #FFAF00")  # Amber/orange
    elif agent.status == "RETRYING":
        countdown = ""
        if agent.retry_next_at_epoch:
            import time

            remaining = max(0, int(agent.retry_next_at_epoch - time.time()))
            countdown = f" ({remaining}s)"
        text.append(f"RETRYING{countdown}", style="bold #FF8700")  # Orange
    else:
        text.append(agent.status, style="dim")
    text.append(")", style="dim")

    # Retry/fallback annotations for RUNNING agents that have retried
    if agent.status == "RUNNING" and agent.retry_count > 0:
        annotation = f" ↻{agent.retry_count}"
        if agent.using_fallback and agent.fallback_model:
            short_name = short_model_name(agent.fallback_model)
            annotation += f"▸{short_name}"
        text.append(annotation, style="bold #FF8700")  # Orange

    # Fold annotation for workflow parents.  ``×N +M`` / ``×N −M`` (with
    # extra hidden/shown info) renders dim; the bare ``×N`` collapsed
    # form keeps its dim-cyan accent so the count still pops.
    if fold_annotation:
        if "+" in fold_annotation or "−" in fold_annotation:
            text.append(fold_annotation, style="dim")
        else:
            text.append(fold_annotation, style="dim #00D7D7")

    # User-managed tag badge.
    if agent.tag:
        text.append(f" @{agent.tag}", style="bold #5FAFFF")  # Sky blue

    # Agent name annotation
    if agent.agent_name:
        text.append(f" @{agent.agent_name}", style="#FFD700")  # Gold

    # Embedded workflow annotation for child steps
    if agent.embedded_workflow_name:
        text.append(" ", style="")
        if agent.is_pre_prompt_step:
            text.append("▲", style="bold #5F87AF")
        else:
            text.append("▼", style="bold #D7AF5F")
        text.append(f"#{agent.embedded_workflow_name}", style="dim #AF87D7")

    suffix = _build_runtime_suffix(agent, now=now)
    option_id = f"{index}:{agent.agent_type.value}:{agent.cl_name}"
    return text, suffix, option_id


def format_banner_option(
    group: GroupRow,
    agents: list[Agent],
    *,
    width: int,
    sequence: int,
    selectable: bool = False,
    mode: GroupingMode = GroupingMode.STANDARD,
    tier_styles: tuple[str, ...] = (),
    hint_char: str | None = None,
) -> Option:
    """Render a group banner row Option.

    Both levels share the shape ``<gutter><prefix> <label> <rule…>  <chip>``
    with the chip right-aligned to ``width`` so banner chips line up with
    the runtime suffix column on agent rows.  ``tier_styles`` injects the
    leading tier-guide gutter (one ``│  `` segment per ancestor L0/L1
    banner).  Glyphs and colors differ by grouping mode:

    - STANDARD L0 (project): bold sky-blue ``▌`` bar + label, dim sky-blue
      heavy rule ``━`` and chip.
    - STANDARD L1 (ChangeSpec, 3-level mode): cooler accent + ``▎`` bar,
      light rule ``─``.
    - BY_DATE L0 (date bucket): bold sky-blue label + heavy rule, no
      project bar — the bucket name is the visual anchor.
    - BY_STATUS L0 (status bucket): leading status glyph (``▲`` for
      ``Needs Attention``) + bold sky-blue label + heavy rule.
    - L1/L2 (name-root) in any mode: dim-gray ``▸`` branch glyph, teal
      label, dim-gray light rule ``─`` and chip.

    Banner Options are marked ``disabled`` so OptionList cursor
    navigation skips them at full expansion.  When *selectable* is True
    (fold level < max) the banner stays in the cursor flow.
    """
    label = banner_label(group)
    summary = compute_banner_summary(group, agents)
    chip = banner_summary_text(summary)

    # Only STANDARD mode uses the ChangeSpec banner row; BY_DATE / BY_STATUS
    # collapse the project + ChangeSpec layers into the bucket so any L1
    # banner there is a name-root banner regardless of agents' cl_name.
    panel_uses_changespec = mode is GroupingMode.STANDARD and any(
        a.cl_name for a in agents
    )
    is_changespec_banner = (
        group.level == 1 and panel_uses_changespec and len(group.group_key) == 2
    )
    if group.level == 0 and mode is GroupingMode.STANDARD:
        prefix = f"{_PROJECT_BAR_GLYPH} "
        rule_char = _PROJECT_RULE
        prefix_style = _PROJECT_BANNER_BAR_STYLE
        label_style = _PROJECT_BANNER_BAR_STYLE
        rule_style = _PROJECT_BANNER_RULE_STYLE
    elif group.level == 0:
        # Bucket banner (BY_DATE / BY_STATUS): drop the project bar so the
        # bucket name leads.  In BY_STATUS mode, prepend a status glyph
        # that signals the bucket's semantics at a glance.
        if mode is GroupingMode.BY_STATUS and label in _STATUS_BUCKET_GLYPHS:
            prefix = f"{_STATUS_BUCKET_GLYPHS[label]} "
        else:
            prefix = ""
        rule_char = _PROJECT_RULE
        prefix_style = _PROJECT_BANNER_BAR_STYLE
        label_style = _PROJECT_BANNER_BAR_STYLE
        rule_style = _PROJECT_BANNER_RULE_STYLE
    elif is_changespec_banner:
        prefix = f"{_CHANGESPEC_BAR_GLYPH} "
        rule_char = _CHANGESPEC_RULE
        prefix_style = _CHANGESPEC_BANNER_BAR_STYLE
        label_style = _CHANGESPEC_BANNER_BAR_STYLE
        rule_style = _CHANGESPEC_BANNER_RULE_STYLE
    else:
        prefix = f"{_NAME_ROOT_BRANCH_GLYPH} "
        rule_char = _NAME_ROOT_RULE
        prefix_style = _NAME_ROOT_BANNER_BRANCH_STYLE
        label_style = _NAME_ROOT_BANNER_LABEL_STYLE
        rule_style = _NAME_ROOT_BANNER_BRANCH_STYLE

    text = _render_tier_gutter(tier_styles)
    gutter_cells = len(tier_styles) * _TIER_GUIDE_SEGMENT_WIDTH
    if hint_char is not None:
        text.append(f"[{hint_char}] ", style="bold #FFFF00")
    hint_cells = 4 if hint_char is not None else 0
    text.append(prefix, style=prefix_style)
    text.append(label, style=label_style)
    if chip:
        # ``<gutter><hint><prefix><label> <rule…>  <chip>``: 1-cell gap
        # before the rule, 2-cell gap before the chip.
        used = gutter_cells + hint_cells + len(prefix) + len(label) + 1 + 2 + len(chip)
        pad_len = max(2, width - used)
        text.append(
            " " + rule_char * pad_len + "  " + chip,
            style=rule_style,
        )
    else:
        used = gutter_cells + hint_cells + len(prefix) + len(label) + 1
        pad_len = max(2, width - used)
        text.append(" " + rule_char * pad_len, style=rule_style)

    # Sequence-prefixed id keeps banner Options unique even when the
    # same group key is split into multiple non-contiguous clusters.
    key_str = "/".join(group.group_key)
    return Option(
        text,
        id=f"group:{sequence}:{group.level}:{key_str}",
        disabled=not selectable,
    )


def format_attempt_option(
    agent: Agent,
    record: AttemptRecord,
    *,
    is_selected: bool,
) -> tuple[Text, Text, str]:
    """Build ``(left_text, suffix_text, option_id)`` parts for a prior-attempt row."""
    text = Text()
    text.append("    ↳ ", style="dim #808080")
    label_style = "bold #FF8700" if is_selected else "#FF8700"
    text.append(f"Attempt {record.attempt_number}", style=label_style)
    try:
        hhmmss = record.start_hhmmss
    except (ValueError, OSError):
        hhmmss = "??:??:??"
    text.append(f" · {hhmmss}", style="dim #FF8700")
    if record.used_fallback:
        text.append(" (fallback)", style="dim #FF8700")
    text.append(f" · {record.status}", style="dim #FF8700")
    if record.error_snippet:
        text.append(f": {record.error_snippet}", style="dim italic #FF5F5F")
    suffix = _build_attempt_runtime_suffix(record)
    option_id = f"attempt:{agent.raw_suffix}:{record.attempt_number}"
    return text, suffix, option_id


class AgentRenderCache:
    """Per-widget LRU cache for agent and banner row rendering.

    Lives on the AgentList instance so each widget owns its own bounded
    cache (separate widgets render independently and a process-wide
    cache would let an idle panel pin entries for an active one).
    """

    def __init__(self) -> None:
        self._agent: OrderedDict[tuple[Any, ...], tuple[Text, Text, str]] = (
            OrderedDict()
        )
        self._banner: OrderedDict[tuple[Any, ...], Option] = OrderedDict()

    def get_agent(self, key: tuple[Any, ...]) -> tuple[Text, Text, str] | None:
        return _bounded_lru_get(self._agent, key)

    def put_agent(self, key: tuple[Any, ...], value: tuple[Text, Text, str]) -> None:
        _bounded_lru_put(self._agent, key, value, maxsize=_AGENT_CACHE_MAX)

    def get_banner(self, key: tuple[Any, ...]) -> Option | None:
        return _bounded_lru_get(self._banner, key)

    def put_banner(self, key: tuple[Any, ...], value: Option) -> None:
        _bounded_lru_put(self._banner, key, value, maxsize=_BANNER_CACHE_MAX)

    def invalidate_agent(self, identity: Any) -> None:
        """Drop every cached entry whose key starts with *identity*.

        Used by ``patch_agent_row`` callers to bust stale renders without
        flushing the whole cache. Keys are tuples whose first element is
        ``agent.identity`` (see :func:`_agent_render_key`).
        """
        stale = [k for k in self._agent if k and k[0] == identity]
        for k in stale:
            self._agent.pop(k, None)

    def clear(self) -> None:
        self._agent.clear()
        self._banner.clear()

    def __len__(self) -> int:
        return len(self._agent) + len(self._banner)


def cached_format_agent_option(
    cache: AgentRenderCache,
    agent: Agent,
    index: int,
    *,
    is_selected: bool,
    fold_annotation: str = "",
    is_expanded: bool = False,
    is_marked: bool = False,
    hint_char: str | None = None,
    now: datetime | None = None,
    tier_styles: tuple[str, ...] = (),
) -> tuple[Text, Text, str]:
    """Memoized wrapper for :func:`format_agent_option`.

    Reuses ``(left, suffix, option_id)`` from *cache* when every input
    matches a prior call. ``Text`` objects from Rich are immutable for
    our purposes (we don't mutate them after assemble); returning the
    cached object avoids rebuilding an O(rows) Text tree on each refresh.
    """
    key = _agent_render_key(
        agent,
        index,
        is_selected=is_selected,
        fold_annotation=fold_annotation,
        is_expanded=is_expanded,
        is_marked=is_marked,
        hint_char=hint_char,
        now=now,
        tier_styles=tier_styles,
    )
    hit = cache.get_agent(key)
    if hit is not None:
        return hit
    parts = format_agent_option(
        agent,
        index,
        is_selected=is_selected,
        fold_annotation=fold_annotation,
        is_expanded=is_expanded,
        is_marked=is_marked,
        hint_char=hint_char,
        now=now,
        tier_styles=tier_styles,
    )
    cache.put_agent(key, parts)
    return parts


def _banner_render_key(
    group: GroupRow,
    agents: list[Agent],
    *,
    width: int,
    sequence: int,
    selectable: bool,
    mode: GroupingMode,
    tier_styles: tuple[str, ...],
    hint_char: str | None,
) -> tuple[Any, ...]:
    """Stable cache key for :func:`format_banner_option`.

    The chip portion of a banner reflects the agent set's status
    distribution, so the key folds in a tuple of ``(identity, status)``
    pairs for that group's agents. ``width`` and ``sequence`` are part
    of the key because they affect the rendered Option directly.
    """
    member_sig = tuple(
        (a.identity, a.status, a.hidden, a.is_workflow_child) for a in agents
    )
    return (
        group.group_key,
        group.level,
        bool(group.is_collapsed),
        width,
        sequence,
        selectable,
        mode,
        tier_styles,
        hint_char,
        member_sig,
    )


def cached_format_banner_option(
    cache: AgentRenderCache,
    group: GroupRow,
    agents: list[Agent],
    *,
    width: int,
    sequence: int,
    selectable: bool = False,
    mode: GroupingMode = GroupingMode.STANDARD,
    tier_styles: tuple[str, ...] = (),
    hint_char: str | None = None,
) -> Option:
    """Memoized wrapper for :func:`format_banner_option`."""
    key = _banner_render_key(
        group,
        agents,
        width=width,
        sequence=sequence,
        selectable=selectable,
        mode=mode,
        tier_styles=tier_styles,
        hint_char=hint_char,
    )
    hit = cache.get_banner(key)
    if hit is not None:
        return hit
    option = format_banner_option(
        group,
        agents,
        width=width,
        sequence=sequence,
        selectable=selectable,
        mode=mode,
        tier_styles=tier_styles,
        hint_char=hint_char,
    )
    cache.put_banner(key, option)
    return option
