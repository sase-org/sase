---
create_time: 2026-06-20 16:18:28
status: done
prompt: sdd/prompts/202606/sase_context_workspaces_lane.md
---
# Show Opened Sibling Workspaces in the "SASE CONTEXT" Panel

## Goal

Two user-facing changes to the agent metadata panel on the **Agents** tab of the `sase ace` TUI:

1. **New WORKSPACES lane.** Surface every sibling/linked workspace an agent opened via `sase workspace open`
   (`-p <repo> -r "<reason>" <num>`), including the **reason** the agent gave. Today that reason is required at the CLI
   but immediately discarded, and the opened workspaces are never shown in the TUI.
2. **Rename the section** from `AGENT CONTEXT` to `SASE CONTEXT`.

The result should be a third lane that sits beside the existing `MEMORY` and `SKILLS` lanes and looks like it always
belonged there — same row grammar, same alignment, a distinct-but-harmonious accent color, and the reason rendered with
the shared `↳` continuation style.

## Product Context

The `SASE CONTEXT` section is the panel's audit of what the agent did with SASE's own tooling. It currently has two
lanes:

- `▸ MEMORY` — audited `sase memory read` events (cyan `◇`).
- `▸ SKILLS` — audited xprompt skill uses (green `◆`).

Each row is `HH:MM:SS [role] <glyph> <primary>` with the reason wrapped underneath as `↳ <reason>`. Lanes hide
themselves when empty, the whole section hides when all lanes are empty, and an agent-family row attributes each event
to the producing member via a compact role column. The new `WORKSPACES` lane must adopt all of these behaviors so the
three lanes stay visually and behaviorally uniform.

Opening a sibling workspace is exactly the kind of audited "what did this agent touch" signal these lanes exist to
surface, so it belongs here rather than in the plain metadata rows above the divider.

## Current Shape

**Recording (the data we will surface).** `sase workspace open` flows through
`src/sase/main/workspace_handler_list.py::handle_open_clean`. When the opened workspace is a sibling, it calls
`record_opened_linked_repo(name, workspace_dir)` in `src/sase/linked_repos.py`, which writes a per-run JSON marker
(`opened_linked_workspaces.json`, plus the legacy `opened_siblings.json`) under `$SASE_ARTIFACTS_DIR`. Each record is
`{name, workspace_dir}` only. The required `-r/--reason` is validated by `_normalize_workspace_open_reason` at the top
of `handle_open_clean` and then thrown away. The marker is read back today only by the commit finalizer
(`opened_linked_repo_names` / `opened_linked_repo_workspace_dirs`).

**Rendering (where the new lane goes).** The section is assembled in pure Python presentation code:

- `_agent_context.py::append_agent_context_section(text, *, memory_reads, skill_uses)` — emits the `AGENT CONTEXT` major
  header (gold underline) then the lanes; gates the whole section on `memory_reads or skill_uses`.
- `_agent_memory_reads.py` / `_agent_skill_uses.py` — per-lane renderers, both built on shared helpers in
  `_agent_context_common.py` (`append_context_lane_header`, `append_lane_row`, `append_context_reason`, `count_phrase`,
  truncation, the color/glyph constants).
- `_agent_display_parts.py` — `_DetailHeaderSummary` holds `memory_reads` / `skill_uses`;
  `build_detail_header_summary(agent)` loads them; `build_header_text(...)` renders the section only on the non-`cheap`
  path, gated on `summary.memory_reads or summary.skill_uses`.

**Loaders (the pattern to mirror).** `memory_reads.py` / `skill_uses.py` each expose a `load_*_for_agent_context(agent)`
that returns display events (with optional family `agent_label`), backed by an mtime-keyed cache + 0.5s throttle, and a
`*DisplayEvent` dataclass. Family attribution is handled by `agent_context_members.py` (`build_context_members`,
`match_event_label`, compact role labels).

**TUI performance.** Per `memory/tui_perf.md`: detail-panel work is debounced and must not run on the immediate j/k
highlight paint. The context lanes already only render on the non-`cheap` path via the precomputed
`_DetailHeaderSummary`, so the new loader runs in the debounced/expensive path — and it must still be cheap and
mtime-cached, mirroring the existing two loaders.

## Architecture / Rust Boundary

Per `memory/rust_core_backend_boundary.md`, shared backend behavior belongs in the Rust core. I evaluated this and
concluded **all changes stay in Python**, for three reasons:

1. The opened-workspace marker schema already lives entirely in Python (`src/sase/linked_repos.py`), written by the CLI
   and read by the Python commit finalizer. Nothing about it is in `sase-core` / `AgentMetaWire` today.
2. The immediately prior `workspace_open_reason` change deliberately scoped this marker as a narrow Python contract and
   chose **not** to expand it into a broader audited schema. Extending the same Python file with one optional field is
   consistent with that decision and avoids reopening a cross-repo schema migration.
3. The new lane is pure Textual presentation, which the boundary doc explicitly keeps in this repo.

So: no `sase-core` changes, no binding changes.

## Design

### 1. Persist the reason (and an open timestamp) — `src/sase/linked_repos.py`

Extend the marker record from `{name, workspace_dir}` to `{name, workspace_dir, reason, opened_at}`:

- Bump `_OPENED_SCHEMA_VERSION` 1 → 2 (the reader already ignores the version when parsing, so old v1 markers keep
  working).
- `record_opened_linked_repo(name, workspace_dir, *, reason="", opened_at=None)` — add two keyword-only params with
  backward-compatible defaults so existing callers/tests keep working. Persist `reason` (normalized/stripped) and
  `opened_at` (ISO-8601 UTC string) in each record. `opened_at` is passed in by the handler (keeps the function pure and
  deterministic for tests).
- `_opened_records(...)` — preserve `reason` and `opened_at` (defaulting to `""`) when reading, so (a) the
  merge-on-write in `record_opened_linked_repo` does not strip these fields off other repos, and (b) a new reader can
  surface them. Old markers lacking the fields read back as empty strings.
- Add a reader `opened_linked_repo_records(artifact_root) -> dict[str, dict[str, str]]` returning the full records (name
  → `{name, workspace_dir, reason, opened_at}`), unioning the canonical + legacy markers like the existing readers.
  Leave `opened_linked_repo_names` / `opened_linked_repo_workspace_dirs` untouched — the finalizer keeps working
  unchanged because `name`/`workspace_dir` are still present.

### 2. Stamp + forward the reason — `src/sase/main/workspace_handler_list.py`

In `handle_open_clean`: capture the normalized reason (currently discarded), stamp an ISO-8601 UTC `opened_at` at record
time (mirroring `read_log._event_timestamp`), and pass both into `record_opened_linked_repo(...)`. The reason validation
gate and exit-code-2 behavior are unchanged; recording still only happens for siblings.

### 3. Loader — new `src/sase/ace/tui/opened_workspaces.py`

Mirror `skill_uses.py` closely:

- `OpenedWorkspaceDisplayEvent` dataclass: `name`, `workspace_dir`, `reason`, `opened_at` (timestamp string), and
  `agent_label: str | None = None` for family rows.
- `load_opened_workspaces_for_agent_context(agent) -> tuple[OpenedWorkspaceDisplayEvent, ...]`, newest-first:
  - **Single member:** read the agent's own artifacts dir (`agent.get_artifacts_dir()`) via
    `opened_linked_repo_records`, wrap each record with no label.
  - **Family:** iterate `build_context_members(agent)`, read each member's artifacts-dir marker, label each record with
    the member's compact role, dedupe by (member, repo), sort newest-first by `opened_at`.
  - mtime-keyed cache + `_MIN_REREAD_INTERVAL_S` throttle on the marker file, exactly like the existing loaders, so the
    debounced detail render stays cheap.
- A private `_load_opened_workspaces_for_agent(agent)` (single-agent path) so the visual-snapshot helper can patch it
  the same way it patches `_load_memory_reads_for_agent` / `_load_skill_uses_for_agent`.

### 4. Rendering — new lane + shared constants

**`_agent_context_common.py`:** add a third color/glyph set that is distinct from cyan (MEMORY) and green (SKILLS) and
from the violet role column, and that does not collide with the gold section header:

- `COLOR_WORKSPACE_SUBHEADER` / `COLOR_WORKSPACE_GLYPH` / `COLOR_WORKSPACE_NAME` / `COLOR_WORKSPACE_PATH` — proposed
  magenta/pink family (`bold #FF87D7` subheader+glyph, `bold #FFAFD7` repo name, dim mauve path), giving a clean
  cyan/green/magenta triad across the three lanes.
- `WORKSPACE_GLYPH` — proposed `⧉` (overlapping squares = linked repos). **Verification step required:** confirm the
  chosen glyph renders in the Fira Code visual-snapshot font; fall back to `▣` if it does not. Add a `→` connector
  constant for the secondary path.

**New `_agent_opened_workspaces.py`** (mirrors `_agent_skill_uses.py`):
`append_agent_opened_workspaces_section(text, *, events, show_empty=False)`:

- Subheader: `▸ WORKSPACES · {N open(s)} · {M repo(s)} [· {A agent(s)}]` via `append_context_lane_header` +
  `count_phrase`.
- Row: `append_lane_row(...)` with the workspace glyph and the **repo name** as the primary; then a dim secondary suffix
  on the same line showing the (truncated) workspace path as `→ …/<repo>_<num>` — structurally the same slot the MEMORY
  lane uses for its `↩ frontmatter` marker. Reason underneath via `append_context_reason` so the `↳` aligns with the
  primary, identical to the other lanes.
- Cap at `MAX_VISIBLE_OPENED_WORKSPACES = 5` with the shared `+ N more · HH:MM earliest` overflow line.

**`_agent_context.py`:** rename the header literal to `SASE CONTEXT`; add an `opened_workspaces` parameter; render the
lane after `SKILLS`. Generalize the inter-lane separator logic to "insert one blank line before each rendered lane
except the first" so any subset of the three lanes spaces correctly (the current two-lane special-case does not extend
cleanly to three). Update the module/docstring wording to "SASE CONTEXT".

**`_agent_display_parts.py`:** add `opened_workspaces` to `_DetailHeaderSummary`; load it in
`build_detail_header_summary` via `load_opened_workspaces_for_agent_context(agent)`; extend the render gate to
`summary.memory_reads or summary.skill_uses or summary.opened_workspaces` and pass the new tuple through to
`append_agent_context_section`.

**Docstring/comment polish:** update the "AGENT CONTEXT" phrasing in `_agent_context_common.py` and
`agent_context_members.py` docstrings to "SASE CONTEXT" for consistency (no behavior change).

### 5. Lane ordering & empty behavior

Order is `MEMORY → SKILLS → WORKSPACES`. Putting the new lane last is the least disruptive to existing snapshots/tests
and reads naturally (reads, then skills, then workspaces opened). Empty-lane and empty-section hiding behavior is
identical to today, now including the third lane: a WORKSPACES-only agent shows `SASE CONTEXT` with just that lane.

## Key Design Decisions (flagged for review)

- **Lane label `WORKSPACES`** (vs `SIBLINGS`/`LINKED`). Chosen because it is parallel with `MEMORY`/`SKILLS`, avoids the
  deprecated "sibling" term while the repo migrates to "linked", and the per-row repo name (e.g. `sase-core`) already
  makes the sibling identity obvious.
- **Persist a timestamp (`opened_at`).** Needed so the lane has the same `HH:MM:SS` column and newest-first ordering as
  the other two; cheap to stamp in the handler.
- **Magenta accent + `⧉` glyph.** Completes a distinct cyan/green/magenta triad; glyph subject to the font-render
  verification step.
- **Reason persisted only in the existing Python marker** (schema v2), not promoted into Rust/`AgentMetaWire`, matching
  the prior change's deliberate scoping.

## Files to Change

Source:

- `src/sase/linked_repos.py` — schema v2, `reason`/`opened_at` in records, new `opened_linked_repo_records` reader.
- `src/sase/main/workspace_handler_list.py` — capture reason, stamp `opened_at`, forward to recorder.
- `src/sase/ace/tui/opened_workspaces.py` — **new** loader + display-event dataclass.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_context_common.py` — workspace color/glyph constants; docstring.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_opened_workspaces.py` — **new** lane renderer.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_context.py` — rename header, add+render third lane, generalize spacing.
- `src/sase/ace/tui/widgets/prompt_panel/_agent_display_parts.py` — summary field, loader call, gate, pass-through.
- `src/sase/ace/tui/agent_context_members.py` — docstring wording.

Tests:

- `tests/test_linked_repos.py` — recording persists/round-trips `reason`+`opened_at`; v1 backward-compat reads empty
  reason; `opened_linked_repo_records` reader.
- `tests/main/test_workspace_handler_list_path.py` — sibling open persists the reason + a timestamp.
- `tests/ace/tui/test_opened_workspaces_loader.py` — **new**: single-agent reads own artifacts dir; family aggregates +
  labels; newest-first; cache/throttle.
- `tests/ace/tui/widgets/test_agent_context.py` — rename `AGENT CONTEXT`→`SASE CONTEXT`; WORKSPACES-only lane;
  three-lane ordering (`MEMORY < SKILLS < WORKSPACES`); distinct magenta subheader color; column/`↳` alignment with the
  other lanes; reason rendering; overflow.
- `tests/ace/tui/widgets/test_prompt_panel_header.py` — rename; opened-workspaces-only path renders the section; cheap
  path still omits it; gate includes the new tuple.
- `tests/ace/tui/visual/_ace_png_snapshot_helpers.py` — add `opened_workspaces=` to `patch_startup_loaders`, patching
  `_load_opened_workspaces_for_agent` like the other two.
- `tests/ace/tui/visual/test_ace_png_snapshots_agents.py` — rename SVG assertion to `SASE CONTEXT`; feed
  opened-workspace events into the context zoom snapshot so the golden shows all three lanes; assert the workspace glyph
  - a repo name; regenerate the PNG golden.

## Validation

Targeted first:

```bash
uv run pytest tests/test_linked_repos.py tests/main/test_workspace_handler_list_path.py \
  tests/ace/tui/test_opened_workspaces_loader.py \
  tests/ace/tui/widgets/test_agent_context.py tests/ace/tui/widgets/test_prompt_panel_header.py
```

Visual (regenerate + eyeball the three-lane golden):

```bash
just test-visual --sase-update-visual-snapshots
```

Then the repo-required full gate:

```bash
just check
```

Notes:

- `sase memory init --check` is unaffected (no generated-memory change); ignore the pre-existing unrelated home-memory
  drift if it appears.
- If `just test` shows failures outside the touched suites, confirm against a clean tree before attributing them to this
  change (recent runs have shown unrelated `sase_core_rs`-binding baseline failures).
