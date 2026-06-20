---
create_time: 2026-06-20 17:54:34
status: done
prompt: sdd/prompts/202606/linked_repo_delta_indicators.md
---
# Linked-Repo Indicators for the Agents-Tab "Deltas:" Section

## Goal

On the Agents tab, the agent metadata panel's `Deltas:` section should make it obvious, at a glance, when a changed file
lives in a **linked repository** (e.g. `sase-core`, `sase-github`) rather than the agent's primary repo. Primary-repo
files keep their current appearance with no prefix or indicator; linked-repo files are grouped under a beautiful,
magenta workspace-accented header that names the repo they belong to.

The indicator must be **intuitive** (you instantly see which repo a file belongs to), **reliable** (it never shows stale
or mis-attributed changes), and **beautiful** (it reuses the workspace visual language already shipped with the
`WORKSPACES` lane: the magenta `▣` glyph and accent colors).

## Critical Finding That Reframes This Request

The request assumes the `Deltas:` list already contains a mix of primary-repo and linked-repo files that simply need
tagging. **It does not.** Investigation of the render path shows:

- The agent diff comes from `get_agent_diff(agent)`, which runs a **single-repo**
  `provider.diff_with_untracked(workspace_dir)` against the agent's **primary** workspace only (or reads a single
  pre-computed `diff_path` for completed agents).
- Linked repos are configured as **sibling** directories (`../sase-core`), never nested inside the primary workspace, so
  a primary `git diff` can never include their files.
- Consequently, a normal agent's `Deltas:` list contains **zero** linked-repo entries today. The one exception is a
  degenerate case (an agent whose _entire_ workspace _is_ a linked repo), where every entry would carry the same prefix.

Therefore a pure "tag the existing entries" feature would be invisible in normal use. The indicator is only meaningful
if the panel **also starts surfacing changes that live in the agent's linked-repo workspaces**. The good news: when we
compute each repo's diff separately, every entry's repo provenance is known for free and with full reliability — there
is no fragile path-prefix guessing.

**This is the scope decision to confirm at review:** the `Deltas:` section will begin showing dirty files from the
agent's linked-repo workspaces (each clearly attributed), in addition to the primary-repo files it shows today. The
alternative — tagging only the degenerate whole-workspace-is-linked case — delivers almost no visible value and is not
recommended.

## Product Design

The `Deltas:` section becomes repo-aware while preserving today's look for the common case:

- **Primary-repo entries render exactly as they do today** — same glyphs (`+ ~ -`), bold-basename path treatment, and
  `+N ~M -D` line stats, with no prefix. An agent that only touches its primary repo sees **no change whatsoever**.
- **Linked-repo entries are grouped** beneath a compact, magenta sub-header per repo, echoing the `WORKSPACES` lane:

```text
Deltas:
  ~ src/sase/ace/foo.py        +3 ~2 -1
  + tests/ace/test_foo.py      +10
  ▣ sase-core
    ~ crates/sase_core/src/editor/completion.rs   +5 ~1
    + crates/sase_core/src/editor/new_mod.rs      +20
  ▣ sase-github
    ~ src/provider.rs           +2 -2
```

Why grouped rather than an inline per-line chip: agents that touch a linked repo usually touch several files in it.
Grouping names the repo once (no noisy repetition), is highly scan-friendly, and is visually cohesive with the
already-shipped magenta `▣` `WORKSPACES` lane. Each indented file under a `▣ <repo>` header unambiguously "belongs to"
that linked repo, satisfying the request's intent. (An inline per-entry chip is the considered alternative — see Review
Decisions.)

Visual grammar:

- Repo sub-header: `▣ <repo-name>` using the shipped workspace accent (`COLOR_WORKSPACE_GLYPH` / `COLOR_WORKSPACE_NAME`,
  `WORKSPACE_GLYPH = "▣"`) from `_agent_context_common.py`, so the indicator color-matches the `WORKSPACES` lane.
- Linked entries are indented one level deeper than primary entries but otherwise use the identical glyph/path/line-stat
  rendering, so a linked file reads as "the same kind of change, just in another repo."
- Ordering: primary entries first (unchanged), then linked groups in a stable order (configured linked-repo order, then
  by repo name), so the panel never reflows unpredictably between refreshes.
- Self-explanatory from structure alone — no prose labels are added to the panel.

## Reliability Design

Correctness rules so the indicator is trustworthy:

- **Active agents only.** Linked-repo deltas are computed live via `git` in each linked workspace. A completed agent's
  numbered linked workspaces may have been released and reused by another agent, so a live read there could show a
  _different_ agent's work. Linked groups are therefore shown **only while the agent is active** (the same status gate
  `get_agent_diff` already uses; completed/failed agents show only their persisted primary diff, exactly as today).
  Surfacing linked deltas for completed agents requires persisting a multi-repo diff at finalization and is deferred
  (see Future Work).
- **Agent-isolated workspaces only.** Only linked repos with the numbered-workspace (`suffix`) strategy — whose
  workspace dir is unique to this agent's workspace number — are eligible. Linked repos using the `none` strategy share
  a single static checkout that is not attributable to one agent (the commit finalizer already classifies these as
  merely "advisory"); they are excluded so the panel never attributes shared/manual edits to this agent.
- **Existence-checked.** A linked workspace dir that does not exist on disk is silently skipped.
- **Clean repos disappear.** A linked repo with no local changes contributes no group (no empty headers).
- **No path guessing.** Provenance is established by _which workspace we diffed_, not by matching path prefixes, so it
  is exact.

## Performance Design (per `memory/tui_perf.md`)

The detail-summary build (`build_detail_header_summary` → `agent_delta_entries` → `get_agent_diff`) currently runs
**synchronously on the Textual event loop** after the 150 ms detail debounce — the primary `git diff` already runs
there. Adding N additional per-linked-repo `git` calls on that path would block the debounced paint and violate tui_perf
rule #1. The design keeps the synchronous render path I/O-free for linked data:

1. **Off-thread computation.** Linked-repo deltas are gathered in a background thread worker (mirroring the existing
   off-thread diff/tools workers and the recently shipped tmux-chooser cache handoff), coalesced last-request-wins on
   agent selection so a held `j`/`k` produces one final computation.
2. **Cheap clean/dirty gate.** For each eligible linked workspace, probe `has_local_changes` (one
   `git status --porcelain`) first; only run the heavier `diff_with_untracked` + parse when the repo is actually dirty.
   Most agents touch zero or one linked repo, so the common case is one cheap probe per configured repo and no full
   diff.
3. **Cache, keyed by mtime + TTL.** Reuse the `_diff.py` caching discipline (per-workspace `.git/index` fingerprint plus
   a short TTL bucket) per linked repo so re-selecting the same active agent within the window does not re-shell `git`.
4. **In-memory handoff to render.** The worker stores the computed linked-delta groups on an app-level cache keyed by
   agent identity, then requests a detail refresh. `build_detail_header_summary` / the deltas renderer read **only** the
   cached groups — never `git` — so the keypress-to-paint path stays fast. On a cold cache the linked groups simply
   aren't shown yet; they appear on the next paint once the worker fills the cache (the established "show cached
   instantly, reload in background" pattern).
5. **No new render-time disk reads for repo discovery.** The set of linked repos and their workspace dirs is read from
   `agent_meta.json` (`linked_repos`) during the _existing_ agent enrichment pass (already cached), so resolving "which
   linked repos does this agent have" costs nothing extra at render time. The expensive
   `resolve_linked_repos_for_project(materialize=True)` path (which can _create_ checkouts) is never used.

## Data Sources

- **Linked-repo set + workspace dirs:** `agent_meta.json["linked_repos"]` (entries: `name`, `workspace_dir`,
  `workspace_strategy`, ...), written at agent launch and already loaded by the TUI's agent enrichment. The `Agent`
  model gains a parsed `linked_repos` accessor; no new file reads on the render path.
- **Per-repo changes:** the same VCS provider methods the primary diff uses — `has_local_changes` (cheap gate) and
  `diff_with_untracked` (full patch), parsed into `DeltaEntry` values by the existing unified-diff parser, then attached
  to their repo group.
- **Precedent:** the commit finalizer's `collect_dirty_state` already aggregates dirty state across `main` + `sibling`
  repos from these same sources; this feature is the read-only TUI analog of that proven pattern.

## Implementation Shape

Carry linked deltas as **grouped structures at the agent-deltas/render layer** rather than adding a field to the shared
`DeltaEntry` model. This keeps the persisted ChangeSpec `DeltaEntry` (and its `.gp` serialization) untouched and
contains the change to the TUI delta path.

Introduce a small grouping type, e.g. `LinkedDeltaGroup(repo_name: str, workspace_dir: str, entries: list[DeltaEntry])`,
produced off-thread and consumed by the renderer.

### Source

- `src/sase/ace/tui/models/agent.py` and `src/sase/ace/tui/models/_loaders/_meta_enrichment.py`
  - Parse `agent_meta.json["linked_repos"]` into a typed, read-only `agent.linked_repos` accessor (name, workspace_dir,
    workspace_strategy). No new disk read — extend the existing enrichment that already loads `agent_meta.json`.
- `src/sase/ace/tui/widgets/file_panel/_linked_deltas.py` (new)
  - `compute_linked_delta_groups(agent) -> list[LinkedDeltaGroup]`: active-agent + `suffix`-strategy + existence gating,
    `has_local_changes` clean/dirty probe, `diff_with_untracked` + parse for dirty repos, per-repo mtime/TTL caching.
    Designed to run **off-thread**.
- The off-thread worker + app cache handoff (mirroring the tmux-chooser cache + the file/tools panel workers)
  - Compute groups on selection (coalesced), publish to an app-level cache keyed by agent identity, request a detail
    refresh. Likely a small mixin alongside the existing detail/diff plumbing (`src/sase/ace/tui/actions/agents/` and
    the app state initializer).
- `src/sase/ace/tui/widgets/prompt_panel/_agent_deltas.py`
  - Extend `append_agent_deltas_section` to render primary entries (unchanged) then the cached linked groups, with
    correct file-hint numbering continued across groups and hint paths resolved against each group's `workspace_dir`.
- `src/sase/ace/tui/widgets/deltas_builder.py`
  - Add a linked-group renderer: magenta `▣ <repo>` sub-header (reusing `_agent_context_common` workspace constants)
    plus indented entries via the existing `_append_entry` (with deeper indent + hint support). Primary rendering
    unchanged.
- No new modal and (expected) no `styles.tcss` change — the indicator is Rich `Text` inside the existing panel.

### Tests

- `tests/ace/tui/widgets/...` deltas rendering
  - primary-only agent: output byte-identical to today (regression guard);
  - mixed: linked entries appear under a magenta `▣ <repo>` header, indented, with line stats; repo name + glyph
    present;
  - file-hint mode: hint numbers continue across primary + linked groups and resolve to the correct absolute path in
    each linked workspace dir.
- linked-delta computation
  - active-agent gate (completed/failed → no groups);
  - `suffix` included, `none` excluded; missing workspace dir skipped; clean repo (`has_local_changes` empty) → no
    group;
  - dedup / stable ordering.
- agent model
  - `linked_repos` parsed from `agent_meta.json`; absent/empty handled.
- performance contract
  - synchronous render reads only the cache and performs **no** linked-repo `git` calls (assert the compute function is
    not invoked on the render path; the worker invokes it).
- visual snapshot
  - a PNG/SVG snapshot of a `Deltas:` section with primary + two linked repos; assert the SVG contains the `▣` glyph,
    both repo names, and a linked file path.

## Validation

Targeted:

```bash
uv run pytest \
  tests/ace/tui/widgets/prompt_panel/ \
  tests/ace/tui/widgets/ \
  tests/ace/tui/models/
```

Visual:

```bash
just test-visual --sase-update-visual-snapshots
just test-visual
```

Full gate:

```bash
just check
```

If the known `uv run` lockfile issue recurs in this workspace, use the installed virtualenv Python (`.venv/bin/pytest`)
for targeted tests, then still run the repo-level `just check`.

## Rust Core Boundary Note

Per `memory/rust_core_backend_boundary.md`: the multi-repo dirty/diff aggregation is domain-ish, but its Python
precedent already lives in this repo (the commit finalizer's `collect_dirty_state`), and the diff/clean-dirty parsing it
relies on is already delegated to the Rust core (`parse_git_local_changes`). This feature reuses those existing Python
seams and keeps only presentation (grouping, glyphs, colors, layout) in this repo. If a non-TUI frontend later needs a
matching multi-repo delta view, the aggregation should be promoted to `sase-core` at that time; doing so now would
duplicate an existing Python pattern with no second consumer.

## Future Work (out of scope)

- **Completed agents:** persist a multi-repo (primary + linked) diff at finalization so finished agents can also show
  tagged linked deltas reliably, without live-reading released workspaces. This extends the commit/finalize path and is
  intentionally deferred.

## Review Decisions

- The `Deltas:` section will begin surfacing dirty files from the agent's linked-repo workspaces (each attributed),
  because tagging-only would be invisible in normal use. **Confirm this behavior change.**
- Indicator style: **grouped** magenta `▣ <repo>` sub-headers (recommended) vs. an inline per-entry chip prefix.
- Linked deltas shown for **active agents only**; completed agents are unchanged (reliability over completeness).
- Only `suffix`-strategy (agent-isolated) linked repos are eligible; `none`-strategy (shared static) repos are excluded.
- Linked-delta computation runs off-thread with a clean/dirty `git status` gate and an app-cache handoff; the
  synchronous render path never shells `git` for linked data.
- The shared `DeltaEntry` model and ChangeSpec persistence are left untouched; provenance is carried as render-layer
  groups.
