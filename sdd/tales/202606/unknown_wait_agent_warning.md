---
create_time: 2026-06-26 17:40:45
status: done
prompt: sdd/prompts/202606/unknown_wait_agent_warning.md
---
# Plan: Warning marker for unknown agents in the "Waiting for:" field

## Product context

On the **Agents** tab of the `sase ace` TUI, selecting an agent shows an agent metadata panel. When the selected agent
is waiting on other agents (via `%wait`), that panel renders a **"Waiting for:"** line listing the agent names being
waited on.

Today every waited-for name is rendered identically, whether or not an agent with that name actually exists. That hides
a useful signal: an agent can legitimately wait on a name that does not yet correspond to any known agent (the user may
simply not have started that dependency yet), but it can also indicate a typo or a stale reference.

**Goal:** render a small, tasteful warning marker (⚠) immediately to the right of any waited-for name that does **not**
match a currently-known agent. This is a passive, informational hint — _not_ an error. It must read as "heads up,
nothing is named this (yet)", because an unknown wait target is sometimes exactly what the user intends.

### Design goals (it must look beautiful)

- The marker hugs the offending name (`deploy ⚠`), so the warning is unambiguously bound to _that_ name in a
  comma-separated list, not the line as a whole.
- It uses a warm amber accent that pops against the panel's cool palette (cyan labels `#87D7FF`, magenta values
  `#FF87D7`, dim-purple countdown `#AF87FF`) without screaming "error" (errors in this panel are red `#FF5F5F`).
- Known names render exactly as they do today — zero visual change when nothing is wrong. The panel stays clean; no
  permanent legend line is added inline (unknown waits are common, so a repeated inline legend would be noise). The
  marker's meaning is documented in the `?` help legend instead.
- The marker appears on the fast j/k navigation path too, so it shows up the instant an agent is selected.

## What "known" means (ground truth)

A waited-for name is **known** if it matches the name of any agent the TUI currently knows about — including
folded/hidden child agents. We deliberately use the _full_ agent set, not just the agents visible in the panels, so that
waiting on a real-but-hidden child agent is **not** falsely flagged.

The full set is the app's `_agents_with_children` list (the canonical superset of root + child agent rows; see
`src/sase/ace/tui/actions/agents/_core.py`). For each agent we collect both:

- its prompt-referenceable name via the existing resolver `agent_prompt_name(agent)`
  (`src/sase/ace/tui/agent_completion.py`) — this returns the **family** name for family-root agents and the
  `agent_name` otherwise, mirroring exactly what `%wait` autocomplete offers; and
- its raw `agent_name`

so that both family-style waits (`%wait foo`) and specific waits (`%wait foo.bar`) resolve correctly. Matching is an
exact string membership test against this set — the stored `waiting_for` names came from this same name space (via
`%wait` completion), so exact matching avoids false positives. Empty/blank names are skipped.

When the known-name set cannot be determined (e.g. no running app context, as in some unit tests), we render with **no**
markers — never a false warning.

### Rust core boundary

Per `memory/rust_core_backend_boundary.md`, shared domain behavior belongs in `../sase-core`. This feature stays in
Python because:

- The "set of agents currently loaded in this TUI" is frontend/presentation state, not backend domain data — it is
  exactly the in-memory `_agents_with_children` list the TUI already maintains.
- The agent-name resolution this builds on (`agent_prompt_name`) already lives in Python (`agent_completion.py`); there
  is no Rust API for agent-name membership today (agent matching/lookup by name is Python-side).
- The change itself is a presentation marker plus a cheap set-membership check.

If/when agent-name resolution is promoted to Rust core, the small `collect_known_agent_names` helper added here should
follow it. This is noted so a future refactor knows where the seam is.

## High-level technical design

### 1. Known-name collection helper (`src/sase/ace/tui/agent_completion.py`)

Add a small, disk-free helper co-located with the existing name logic:

- `collect_known_agent_names(agents: Iterable[Agent]) -> frozenset[str]` — iterate the agents, add
  `agent_prompt_name(agent)` and `agent.agent_name` (when truthy) to a set, return it frozen.
- `known_agent_names_for_app(app: object) -> frozenset[str] | None` — defensively read `app._agents_with_children` (fall
  back to `app._agents`); return `None` when neither is available/non-empty.

Both are pure and cheap (string ops only, no disk, no `get_raw_xprompt_content`), so they are safe on the hot render
path.

### 2. Render the marker (`src/sase/ace/tui/widgets/prompt_panel/_agent_display_header.py`)

- Define module-level constants next to the other glyph escapes already in this file (`─`, `⚡`):
  - `_UNKNOWN_WAIT_AGENT_ICON = "⚠"` — bare ⚠ WARNING SIGN (text presentation; **no** `️`, so our style applies and the
    cell width stays predictable).
  - `_UNKNOWN_WAIT_AGENT_ICON_STYLE = "bold #FFAF5F"` — the established warning amber (`#FFAF5F` is the repo's
    `_WARN_COLOR`), bold for visibility, harmonizing with the warm `#FFAF00` retry-chain glyph already in this panel.
- Add a keyword-only parameter to `build_header_text`: `known_agent_names: frozenset[str] | None = None`.
- Restructure the "Waiting for:" block (currently lines ~206-243) so the **agent-name segment** is appended name by name
  instead of as one `", ".join(...)` blob:
  - For each name: append `", "` separator (except the first) in the existing value style `#FF87D7`, then the name in
    `#FF87D7`. If `known_agent_names is not None` and the name ∉ the set, append `" "` + the ⚠ icon in the icon style.
  - Preserve the existing `" + "` join between the names segment and the duration/`until` segment, and keep the
    live-countdown suffix logic unchanged. Output for the all-known case must be byte-for-byte identical to today.

### 3. Thread the known-name set through the three render paths

All three `build_header_text` callers are methods on the `AgentPromptPanel` widget (which exposes `self.app`):

- `update_header_only` — `src/sase/ace/tui/widgets/prompt_panel/_agent_display.py` (cheap j/k path)
- `_update_display_impl` — `src/sase/ace/tui/widgets/prompt_panel/_agent_display_render.py` (full path)
- `update_display_with_hints` — `src/sase/ace/tui/widgets/prompt_panel/_agent_display_hints.py` (hints path)

At each call site, compute the set **only when the selected agent is actually waiting** (micro-optimization + clarity),
and pass it down:

```python
known = known_agent_names_for_app(getattr(self, "app", None)) if agent.waiting_for else None
header_text, ... = build_header_text(agent, ..., known_agent_names=known)
```

Access to `self.app` must be defensive (wrap/guard so a missing app context yields `None`, not an exception), so
fake-panel tests and non-app contexts degrade gracefully to "no markers".

### 4. Document the marker in the help legend (`src/sase/ace/tui/modals/help_modal/agents_bindings.py`)

Add one entry to the existing **"Agent Row Glyphs"** legend (the list around lines 255-271), e.g.
`("⚠", "Unknown waited-for agent")`. Keep the description within the help modal's 32-char limit / 57-char box width (per
`src/sase/ace/CLAUDE.md`). This satisfies the "update the `?` help popup" rule and gives the marker a discoverable
meaning without cluttering the panel.

## Testing

1. **Unit tests for `build_header_text`** (extend `tests/ace/tui/widgets/` — e.g. a new
   `test_agent_display_waiting_warning.py`, following the existing `.plain`/`.spans` assertion style):
   - Unknown name → output contains ⚠, with a span carrying `bold #FFAF5F` positioned right after the name.
   - All-known names → no ⚠ anywhere; assert the line text matches the current format exactly (regression guard for the
     restructured join logic, including the `+ duration` / `until` / countdown variants).
   - Mixed list → marker only after the unknown name(s).
   - `known_agent_names=None` → no ⚠ (safe default).

2. **Unit tests for the helpers** (`collect_known_agent_names` / `known_agent_names_for_app`): family-root agent
   contributes its family name; specific agent contributes its `agent_name`; blanks skipped; missing app → `None`.

3. **PNG visual snapshot** (add to `tests/ace/tui/visual/test_ace_png_snapshots_agents_zoom.py`, goldens under
   `tests/ace/tui/visual/snapshots/png/`): patch startup loaders with **two** agents — a WAITING agent whose
   `waiting_for = ["coder", "ghost_deploy"]`, plus a real agent named `coder` — so the app's known-name set contains
   `coder` but not `ghost_deploy`. Open the metadata zoom modal and capture a new golden (e.g.
   `agents_waiting_unknown_zoom_modal_120x40`). This demonstrates the beautiful end state: `coder` clean,
   `ghost_deploy ⚠` marked. Generate with `--sase-update-visual-snapshots`.
   - **Verification step:** inspect the generated PNG to confirm Fira Code (the pinned visual font) renders ⚠ cleanly
     (correct color, single text-cell, no tofu/misalignment). If it renders poorly, fall back to an equally-distinct
     glyph and update the legend + goldens accordingly.

4. **No churn to existing goldens expected:** the current metadata-panel fixtures (`_zoom_agent`, `agents()`) set no
   `waiting_for`, so existing goldens have no "Waiting for:" line. Run the full visual suite to confirm; if any
   pre-existing golden does include a waiting agent whose names aren't in its fixture's agent set, the new ⚠ is correct
   behavior — review and re-baseline that golden intentionally.

5. Run `just check` (after `just install`) plus `just test-visual`.

## Files touched

- `src/sase/ace/tui/agent_completion.py` — add `collect_known_agent_names`, `known_agent_names_for_app`.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_header.py` — icon constants, new param, per-name render.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_display.py` — pass known set (cheap path).
- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_render.py` — pass known set (full path).
- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_hints.py` — pass known set (hints path).
- `src/sase/ace/tui/modals/help_modal/agents_bindings.py` — legend entry.
- `tests/ace/tui/widgets/test_agent_display_waiting_warning.py` (new) — unit tests.
- `tests/ace/tui/visual/test_ace_png_snapshots_agents_zoom.py` (+ new golden PNG) — visual test.

## Out of scope

- The Wait modal (`src/sase/ace/tui/modals/wait_modal.py`) and the agent **row** rendering are unchanged; this feature
  is scoped to the metadata panel's "Waiting for:" line, as requested.
- No change to how waits are resolved/satisfied or to `%wait` completion behavior.
