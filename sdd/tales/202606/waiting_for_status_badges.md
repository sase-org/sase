---
create_time: 2026-06-26 18:27:12
status: done
---
# Plan: Live status badges for each agent in the "Waiting for:" field

## Product context

On the **Agents** tab of the `sase ace` TUI, selecting an agent shows a metadata panel. When the selected agent is
waiting on other agents (via `%wait`), the panel renders a **"Waiting for:"** line listing the agent names being waited
on (e.g. `Waiting for: coder, builder + 2m30s`).

Today those names are inert text. A user staring at a fan-out of waits cannot tell, at a glance, **which dependencies
have already finished, which are still running, which failed, and which don't exist yet** — they have to go hunting
through the Agents list. This feature puts that answer right next to each name: a small, colored **status badge** that
shows each waited-for agent's live state (running / waiting / starting / done / failed / stopped), plus the existing
"unknown name" signal.

This **extends and supersedes** the just-shipped unknown-waited-for-agent marker (commit `f9b635df2`). That feature
appended a bare warning glyph after names with no matching agent. We now generalize it: every waited-for name gets
exactly **one** trailing badge — its agent's status glyph when the name is known, or a distinct "unknown" glyph when no
agent has that name. The two concepts become one coherent per-name badge.

### Design goals

It must be **intuitive, reliable, and beautiful**:

- **Intuitive** — the badges reuse the TUI's _existing_ status vocabulary. The Agents tab already groups agents under
  bucket banners with glyphs `▶ Running`, `⏳ Waiting`, `◐ Starting`, `✓ Done`, `✗ Failed`, `▲ Stopped`
  (`AGENT_STATUS_BUCKET_GLYPHS` in `src/sase/agent/status_buckets.py`, documented in the `?` help "Grouping" section). A
  user already knows `✓` = done and `✗` = failed; we speak the same language, so no new vocabulary to learn.
- **Reliable** — status is derived through the single canonical mapping `status_bucket_for_values()` (the same function
  the Agents list uses), so all status strings — including the many plan/tale/handoff variants — resolve correctly, not
  just the four obvious ones. Name resolution reuses the existing prompt-name resolver, and the helper degrades to "no
  badges" (never a wrong badge) whenever the agent set can't be determined.
- **Beautiful** — each badge is a single, warm/cool-balanced glyph that hugs its name (`coder ✓`, `builder ▶`), colored
  with the established agent-row status palette. The dependency names keep their calm magenta value color; only the
  small glyph carries the status accent, so the line stays scannable rather than turning into a rainbow.

## The status vocabulary (ground truth + collision fix)

For each waited-for name we resolve to **at most one** badge:

| Bucket (from `status_bucket_for_values`) | Glyph | Style          | Mirrors agent-row color |
| ---------------------------------------- | ----- | -------------- | ----------------------- |
| `Running`                                | `▶`   | `bold #FFD700` | RUNNING (gold)          |
| `Waiting`                                | `⏳`  | `bold #AF87FF` | WAITING (amethyst)      |
| `Starting`                               | `◐`   | `bold #87D7FF` | STARTING (sky)          |
| `Done`                                   | `✓`   | `bold #5FD75F` | DONE (green)            |
| `Failed`                                 | `✗`   | `bold #FF5F5F` | FAILED (red)            |
| `Stopped`                                | `▲`   | `bold #8787AF` | STOPPED (grey-purple)   |
| _no matching agent_ (unknown)            | `?`   | `bold #FFAF5F` | warning amber (new)     |

The six known-status glyphs are **exactly** `AGENT_STATUS_BUCKET_GLYPHS`; the six colors are **exactly** the agent-row
per-status colors (`src/sase/ace/tui/widgets/_agent_list_render_agent.py`, `models/agent_status.py`). This keeps the
field in lockstep with the rest of the TUI.

**Glyph-collision fix (required).** The just-shipped unknown marker reused `▲`, but `▲` is the canonical **Stopped**
bucket glyph — so `▲` currently means two different things and is even documented twice in the help modal (`▲ Stopped`
under "Grouping" and `▲ Unknown waited-for agent` under "Agent Row Glyphs"). This plan resolves the collision the right
way: in this field `▲` consistently means **Stopped** (matching everywhere else), and the genuinely new "no such agent"
concept gets its own glyph `?` (bold amber) — universally read as "unknown", ASCII-safe in every font.

### What "known" means and how multiple matches aggregate

A name is **known** if it matches the prompt-referenceable name (`agent_prompt_name(agent)`, i.e. the family name for
family roots, else `agent_name`) or the raw `agent_name` of any agent the TUI currently knows about — using the **full**
`_agents_with_children` superset (so waiting on a real-but-folded child is never flagged unknown). This is the same name
space `%wait` autocomplete offers, so exact membership avoids false positives. Unknown names (no match) get the `?`
badge.

A family-style wait (`%wait foo`) can match **several** agents (`foo`, `foo.1`, `foo.bar`). We pick one badge
deterministically via a documented precedence that answers "is this dependency satisfied / does it need attention?":

```
Running > Starting > Waiting > Done > Stopped > Failed
```

So any still-active generation wins (the wait isn't satisfied yet); when all matches are terminal, a `Done` outweighs a
`Failed`/`Stopped`. This is naturally **retry-aware** without special-casing retry flags: `foo.1 FAILED` + `foo.2 DONE`
→ `Done`; `foo.1 FAILED` + `foo.2 RUNNING` → `Running`; all-failed → `Failed`. The overwhelmingly common single-match
case is just that agent's bucket.

### Rust core boundary

Per `memory/rust_core_backend_boundary.md`, this stays in Python: the "set of agents currently loaded in this TUI" is
presentation state (the in-memory `_agents_with_children` list), the name resolver (`agent_prompt_name`) already lives
in Python, and the work is a cheap, presentation-only badge + set/dict lookup. The status→bucket mapping
(`status_bucket_for_values`) is reused as-is. The bucket→(glyph, color) badge palette is pure TUI presentation and lives
in the prompt-panel module. If agent-name resolution is ever promoted to Rust core, the small collection helper here
should follow it (noted as the seam, consistent with the prior plan).

## High-level technical design

### 1. Name → status-bucket collection helper (`src/sase/ace/tui/agent_completion.py`)

Replace the prior unknown-marker helpers (`_collect_known_agent_names` / `known_agent_names_for_app`, used **only** by
the three render paths + their test) with a richer, still disk-free pair:

- `_collect_agent_status_buckets(agents) -> dict[str, str]` — for each agent, map both `agent_prompt_name(agent)` and
  `agent.agent_name` (when truthy) to `status_bucket_for_values(agent.status)`, applying the precedence above when a
  name already has a bucket. The dict's **keys are exactly the known-name set**, so "unknown" = "not a key".
- `agent_status_buckets_for_app(app) -> dict[str, str] | None` — defensively read `_agents_with_children` (fall back to
  `_agents`); return `None` when neither is available/non-empty (no app context ⇒ render no badges).

Both are pure and cheap (string + status ops, no disk), safe on the hot j/k render path.

### 2. Render the badges (`.../prompt_panel/_agent_display_header.py`)

- Define a module-level badge map `_WAIT_STATUS_BADGES: dict[str, tuple[str, str]]` (the table above), with a comment
  noting the glyphs mirror `AGENT_STATUS_BUCKET_GLYPHS` and the colors mirror the agent-row status palette. Replace the
  current `_UNKNOWN_WAIT_AGENT_ICON = "▲"` with `_UNKNOWN_WAIT_AGENT_GLYPH = "?"` (keep the amber `bold #FFAF5F` style).
- Change `build_header_text`'s keyword-only param from `known_agent_names: frozenset[str] | None` to
  `agent_status_buckets: Mapping[str, str] | None = None` (keyword-only, default `None` — every other
  `build_header_text` caller stays source-compatible).
- In the "Waiting for:" per-name loop: after appending each name (unchanged magenta value style), when
  `agent_status_buckets is not None`, append a space + one badge: look up `agent_status_buckets.get(name)`; a present
  bucket → its `_WAIT_STATUS_BADGES` glyph/style; a missing bucket → the `?` unknown glyph/style. When the map is `None`
  (no app context), append no badge. The `+ duration` / `until` / live-countdown logic is untouched.

### 3. Thread the bucket map through the three render paths

The three `build_header_text` callers are `AgentPromptPanel` methods (all expose `self.app`):

- `update_header_only` — `_agent_display.py` (cheap j/k path)
- `_update_display_impl` — `_agent_display_render.py` (full path)
- `update_display_with_hints` — `_agent_display_hints.py` (hints path)

Each currently computes `known_agent_names_for_app(...) if agent.waiting_for else None`; swap to
`agent_status_buckets_for_app(getattr(self, "app", None)) if agent.waiting_for else None` and pass
`agent_status_buckets=...`. Compute only when the selected agent is actually waiting (cheap + clear), and keep the
defensive `getattr(self, "app", None)` so non-app contexts degrade to no badges.

### 4. Update the `?` help legend (`.../modals/help_modal/agents_bindings.py`)

- Remove the now-incorrect `("▲", "Unknown waited-for agent")` entry from "Agent Row Glyphs" (it collided with
  `▲ Stopped`).
- Add a small, discoverable explanation that the "Waiting for:" names carry status badges: a compact entry mapping the
  shared status glyphs to dependency status and a `?` = "waited-for name not found" entry. Wording is finalized during
  implementation against the help-modal limits (≤32-char descriptions, 57-char box width per `src/sase/ace/AGENTS.md`),
  reusing the glyph meanings already documented in the "Grouping" section to avoid duplication.

## Testing

1. **Unit — badge rendering** (extend `tests/ace/tui/widgets/test_agent_display_waiting_warning.py`, `.plain`/`.spans`
   style): each bucket renders its expected glyph with the expected color span right after the name (`Done`→`✓` green,
   `Running`→`▶` gold, `Failed`→`✗` red, `Waiting`→`⏳` amethyst, `Starting`→`◐` sky, `Stopped`→`▲` grey-purple);
   unknown name → `?` amber; mixed list badges each name independently; `agent_status_buckets=None` → no badges (safe
   default); duration / `until` / countdown suffixes still render correctly after the badges.
2. **Unit — helpers**: `_collect_agent_status_buckets` maps family-root → family name and specific agent → `agent_name`,
   both carrying the right bucket; the precedence rule resolves multi-match families (e.g. `FAILED`+`DONE`→`Done`,
   `FAILED`+`RUNNING`→`Running`); blanks skipped; missing app → `None`.
3. **PNG visual snapshot** (`tests/ace/tui/visual/test_ace_png_snapshots_agents_zoom.py`, golden under
   `tests/ace/tui/visual/snapshots/png/`): extend the existing `_waiting_unknown_agents()` fixture so the selected
   `WAITING` agent waits on a small set that showcases the end state — a `DONE` dep (`✓`), a `RUNNING` dep (`▶`), a
   `FAILED` dep (`✗`), and an unknown name (`?`) — with matching agents present in the app set. Regenerate the
   `agents_waiting_unknown_zoom_modal_120x40` golden with `--sase-update-visual-snapshots` and **inspect the PNG** to
   confirm each glyph renders as a clean single cell in the right color.
   - **Fira Code note:** the pinned snapshot font is Fira Code, which lacks emoji glyphs (this is why the prior feature
     fell back from `⚠`). The geometric/dingbat/ASCII badges (`▶ ◐ ✓ ✗ ▲ ?`) are expected to render cleanly. The
     `Waiting` glyph `⏳` is emoji-range and likely renders as tofu **in Fira Code only** — but it renders fine for real
     users (the Agents-tab grouping banners already use `⏳` in production). So the showcase fixture **deliberately
     omits a `Waiting`-status dependency** to keep the golden tofu-free, while `⏳` stays the in-code Waiting glyph for
     consistency with the banners and is covered at the (font-independent) unit-test level. If we later want pixel
     coverage of the Waiting badge, swap to a Fira-Code-safe glyph and update the badge map, legend, and goldens
     together.
4. **No churn to unrelated goldens:** other metadata fixtures set no `waiting_for`, so they have no "Waiting for:" line.
   Run the full visual suite to confirm; re-baseline intentionally only if a pre-existing waiting fixture surfaces a
   correct new badge.
5. Run `just check` (after `just install`) plus `just test-visual`.

## Relationship to the just-shipped unknown marker

This supersedes commit `f9b635df2`: the standalone `▲` unknown marker becomes one case (`?`) of the unified per-name
badge, the `known_agent_names` plumbing becomes the `agent_status_buckets` plumbing, and the prior plan's "known names
render exactly as today" guarantee is **intentionally** lifted — known names now show their status badge, which is the
whole point of this request. The prior feature's tests are updated accordingly (known names now carry badges; the
unknown marker is `?`, not `▲`).

## Files touched

- `src/sase/ace/tui/agent_completion.py` — replace known-name helpers with `_collect_agent_status_buckets` /
  `agent_status_buckets_for_app`.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_header.py` — badge map + `?` unknown glyph, param rename,
  per-name badge render.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_display.py` — thread bucket map (cheap path).
- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_render.py` — thread bucket map (full path).
- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_hints.py` — thread bucket map (hints path).
- `src/sase/ace/tui/modals/help_modal/agents_bindings.py` — fix the `▲`/Stopped collision, document badges + `?`.
- `tests/ace/tui/widgets/test_agent_display_waiting_warning.py` — extend to badge + helper coverage.
- `tests/ace/tui/visual/test_ace_png_snapshots_agents_zoom.py` (+ regenerated golden PNG) — multi-status showcase.

## Out of scope

- The Wait modal (`src/sase/ace/tui/modals/wait_modal.py`) and agent **row** rendering are unchanged; this is scoped to
  the metadata panel's "Waiting for:" line.
- No change to how waits are resolved/satisfied or to `%wait` completion behavior.
- No live re-render on dependency status change beyond the existing selection/refresh paths — the badge reflects the
  agent set as of the current render, exactly like the unknown marker does today.
- The dependency **name** keeps its magenta value color (status-tinting the name itself was considered and rejected to
  keep the line calm and readable).
