---
create_time: 2026-06-24 17:39:37
status: done
prompt: sdd/prompts/202606/agent_name_completion.md
---
# Plan: Agent-name completion for the `%wait` directive and the `#fork` xprompt

## Goal

When a user is composing a prompt and types the argument of **`%wait`** or **`#fork`**, pop an inline completion menu of
the **agent names that are currently visible on the Agents tab** of the `sase ace` TUI. Each row should be beautiful and
immediately legible: a colored status indicator, the agent's name (the exact string that gets inserted), a **visual
indication of which VCS xprompt workflow the agent used** (e.g. `#gh:sase`), and a **short snippet of the agent's
prompt** so the user instantly recognizes which agent they're picking.

This is the agent-argument analogue of the recently-shipped `%model:` value completion, but the data source and the two
trigger grammars are different, and those differences drive the design below.

## Why this is different from `%model:` (read first — it reshapes the design)

The `%model:` work had three properties that **do not hold here**, and the design must account for each:

1. **The candidate source is live TUI state, not a global registry.** "Agents currently visible on the Agents tab" is
   computed from in-process Textual widget state — the focused `AgentList`'s rendered rows (`visible_agents()`), its
   collapsed/folded groups, the `STARTING`-row filter, and `h`/`l` hide/reveal. There is **no on-disk artifact that
   reproduces "what is visible right now"**, and the set changes continuously as agents launch and complete. The model
   registry, by contrast, was static, global, and safe to materialize to a file. **This makes the feature fundamentally
   a TUI feature** (see "Front-end scope" — this is the most important design call).

2. **Two different trigger grammars share one candidate source.** `%wait` is a **directive** argument (same code path as
   `%model:`), and it is **multi-value** (`%wait:a,b` and `%wait(a, b, time=5m)`). `#fork` is an **xprompt** argument (a
   _different_ completion path), and it is **single-value** (`#fork:name` / `#fork(name)`). The design must feed one
   shared agent-candidate provider into both paths so they can never drift.

3. **The candidate list already exists — reuse it, don't reinvent it.** The "agent wait modal" (opened with `w`) already
   builds precisely the list we want: it reads the focused panel's `visible_agents()`, maps each to a
   `WaitAgentCandidate` (name, status, model, runtime, role, tag), excludes unnamed/duplicate agents, and inserts the
   canonical name into a `%wait(...)` directive. Our inline completion should **share that same provider** so the modal
   and the inline menu present identical agents with identical names.

## Background / current state

- **`%wait` directive** is registered in the Rust core (`takes_argument: true`, `allows_multiple: true`, alias `w`) and
  in Python (`_KNOWN_DIRECTIVES`, `_MULTI_VALUE_DIRECTIVES`). Today its argument completion returns only
  **placeholders** ("agent", "time=5m", "time=1h") — never real agent names.
- **`#fork` xprompt** (`src/sase/xprompts/fork.yml`) declares a single optional `name` input of `type: word`. The TUI's
  xprompt-argument completion derives its behavior purely from the input's `type`: `path` → path completion, `bool` →
  `true`/`false`, everything else (including `word`) → a no-op "type hint" with **no value candidates**. So `#fork:`
  currently offers nothing.
- **The TUI prompt-input completion pipeline is pure Python** (open → refresh → render → accept). The Rust xprompt LSP
  is a **separate** completion engine used only by Neovim. The `%model:` work touched both; this feature, by the scope
  decision below, touches only the Python TUI path.
- **The wait modal's candidate machinery** lives in `src/sase/ace/tui/actions/agents/_wait_resume.py`
  (`_visible_wait_candidate_agents()` → `visible_agents()`; `_wait_candidate_from_agent()`; `_agent_prompt_name()` which
  computes the canonical insertable name) and `src/sase/ace/tui/modals/wait_modal.py` (`WaitAgentCandidate`, the
  status-colored row renderer, the comma-fragment search).
- **Per-agent data available now:** `Agent.agent_name` / agent-family name (the insertable string), `status`, `model` /
  `llm_provider` / `reasoning_effort`, `vcs_provider` (provider type only), `tag`. The **prompt text** is not a field;
  it is a cached, mtime-keyed disk read via `agent.get_raw_xprompt_content()` (`raw_xprompt.md`). The **VCS workflow
  tag** an agent used is **not** stored separately — it must be parsed back out of that raw prompt with the existing
  `extract_vcs_workflow_tag()` / `extract_project_from_vcs_tag()` / `get_display_name()` helpers.

## The pivotal design decision — Front-end scope: **TUI-only for v1**

I am leading this call deliberately. **v1 implements the feature only in the ACE TUI, not in the Neovim xprompt LSP**,
and that is the right design — not a shortcut:

- The feature's data source, as specified, is _"agents currently visible on the Agents tab in the TUI."_ That visibility
  is live Textual widget state with **no faithful cross-process representation**. The LSP runs in a separate process and
  has no Agents tab.
- The `%model` LSP bridge worked because the model catalog is static and materialized once at launch. An agent list
  materialized at LSP launch would be **stale within seconds** and would not equal "currently visible" — directly
  violating the _reliable_ goal. Showing a misleading agent list in Neovim would be worse than showing none.
- The TUI completion pipeline is **pure Python**, so the full feature ships with **zero Rust changes**. This keeps the
  change focused and avoids the cross-frontend boundary entirely.
- **Boundary check (`rust_core_backend_boundary.md`):** the _grammar_ for recognizing `%wait:` / `#fork:` argument
  positions is shared backend logic — and it **already exists** in the Rust core. The _candidate data_ (which agents are
  visible) is, by definition, TUI-presentation state, not shared domain behavior. So nothing new crosses the boundary.

**Documented follow-up (out of scope for v1):** Neovim/LSP agent completion. It would require a deliberate, separate
decision about what "agents" even means outside the TUI (likely a live-updated on-disk index of recent/active agents,
re-read fresh per request like the VCS catalog) and would explicitly _not_ carry "visible-on-the-tab" semantics. Calling
this out so the reviewer can approve the TUI-only v1 with eyes open, or ask for the LSP path as a second phase.

## Single source of truth: a shared agent-candidate provider

To guarantee the wait modal, `%wait:` completion, and `#fork:` completion never drift, factor one provider that all
three consume:

- **New module** `src/sase/ace/tui/agent_completion.py` exposing:
  - `AgentCompletionCandidate` — the enriched candidate: `name` (the canonical insertable string), `label`, `status`,
    `model`, plus the two new fields **`vcs_workflow`** (workflow type + project ref + provider display, for the badge)
    and **`prompt_snippet`** (a cleaned, directive/tag-stripped one-line excerpt).
  - `build_agent_completion_candidates(visible_agents, *, exclude_identity=None)` — maps visible `Agent`s to candidates,
    reusing the existing canonical-name logic (`_agent_prompt_name`) and skipping unnamed/duplicate agents.
  - VCS workflow badge styling (glyph/short-tag + per-workflow color), see "Beautiful rendering".
- **Refactor** `_wait_resume.py` / `wait_modal.py` to consume this provider (the modal keeps its current columns; it can
  optionally adopt the new VCS badge for visual consistency — secondary polish).
- The inline completion (both paths) consumes the same provider.

The **canonical insertable name** is whatever `_agent_prompt_name()` already returns (agent-family name for family
roots, else `agent_name`); agents without such a name are skipped because they cannot be referenced by `%wait`/`#fork`
anyway. This matches exactly what the wait modal inserts today.

## Sourcing the live agent list from the prompt input

The prompt-input completion code does not currently reach agent state, but it can via `self.app`. Centralize the "which
panel / what's visible" logic in **one app-level accessor** (generalize the wait action's existing
`_visible_wait_candidate_agents()` into a public `visible_agent_completion_candidates()` on the app), and have both the
wait action and the completion touch points call it. Composing a _new_ prompt has no "self" agent, so no exclusion is
applied (unlike the modal, which excludes the selected row).

## Design — `%wait` (directive-argument path)

Mirror the `%model:` work in `directive_completion.py`:

1. **Candidate branch.** In `build_directive_arg_completion_candidates()`, special-case `wait` (like `model`) to
   delegate to an agent builder that filters the shared catalog by the active token and builds `CompletionCandidate`s
   carrying the agent metadata (name/status/vcs/snippet) for the renderer. `effort`/`auto`/`model` keep their paths.
2. **Directive-aware, comma-segmented token boundary.** `extract_directive_arg_token_around_cursor()` already resolves
   the canonical directive name before scanning the value. For `wait`:
   - Accept agent-name characters (letters, digits, `_`, `-`, **`.`** for agent families) in the token predicate.
   - Treat the value as a **comma-separated list** and complete only the **active fragment** (after the last `,`,
     leading space trimmed) — mirroring the modal's `_active_fragment`/`_replace_active_fragment`. Acceptance replaces
     only that fragment, leaving prior names intact.
   - If the active fragment is the `time=` keyword (contains `=`), offer **no** agent candidates.
   - Support **both** the colon form (`%wait:a,b`) **and** the paren form (`%wait(a, b, time=5m)`) — the paren form
     matters because the wait modal itself emits `%wait(...)`.
   - Leave `%effort:` / `%auto:` / `%model:` boundary behavior **byte-for-byte unchanged** (regression tests).
3. **Gating:** reuse the existing `auto_directive_menu` setting. No new config.

## Design — `#fork` (xprompt-argument path)

Introduce a small, **declarative, reusable** value-type rather than special-casing one xprompt name:

1. **New input type `agent`.** Add an `agent` branch to `_completion_kind_for_input()` → new completion kind
   `xprompt_arg_agent`, and route that kind in `build_xprompt_arg_completion_candidates()` to the shared agent builder
   (filtered by the active token).
2. **`fork.yml`:** change `name.type: word` → `type: agent`. Any future xprompt that takes an agent name gets this
   completion for free by declaring `type: agent`.
3. **Runtime parity check:** confirm `type: agent` coerces identically to `word` at xprompt argument-parsing time (it is
   just a string handed to the resume resolver) and is not rejected by any input-type validation. **Fallback** if the
   type extension proves invasive: detect the active xprompt being `fork` and route to the agent builder by name. (The
   `type: agent` approach is preferred; the fallback is the contingency.)
4. **Gating:** reuse the existing xprompt-argument auto-completion gating. No new config.

Both forms (`#fork:name`, `#fork(name)`) complete; acceptance replaces the value token, consistent with the existing
xprompt-arg accept path.

## Design — Beautiful, unified rendering

One shared row renderer (`_append_agent_completion_row()` in `_prompt_input_bar_completion.py`) used by **both** the
`%wait` directive-arg kind and the `#fork` xprompt-arg kind, so the two are visually identical. Compact single line,
borrowing the wait modal's visual grammar (colored status bullet + bold name + dim metadata):

```
●  agent-name        #gh:sase     Redesign the agent wait modal to…
^  ^                 ^            ^
|  bold (inserted)   VCS badge    dim prompt snippet (directives/tags stripped, truncated)
status bullet        (per-workflow color)
```

- **Status bullet** — reuse the wait modal's `_status_style` palette (running/waiting/done/failed colors) so the inline
  menu and the modal read the same.
- **Agent name** — bold; this is the exact string inserted.
- **VCS workflow badge** — the requested "visual indication of which VCS workflow the agent used." Render the agent's
  workflow tag in the user's own mental model (`#gh:sase`), **colored per workflow** via a new small `vcs_workflow`
  style helper (ASCII-safe colored short tag, **not** exotic nerd-font glyphs, for rendering reliability). Agents with
  no VCS tag show a dim neutral marker (e.g. `local`/`·`).
- **Prompt snippet** — `agent.get_raw_xprompt_content()` with leading `%directives` and the VCS tag stripped, collapsed
  to one line and truncated (reusing the existing prompt-summary/VCS-parse helpers where possible). Dim styling.
- The completion panel border title reads e.g. `wait agents` / `fork agent`.

The VCS badge + snippet should also be available to the wait modal rows (optional consistency polish, since the modal
now shares the same enriched candidate).

## Performance (this touches the keystroke/refresh path — `tui_perf.md` reviewed)

- **Build the rich catalog once, at menu open; filter in-memory on refresh.** Snapshot the enriched candidate list
  (which includes the mtime-cached `raw_xprompt.md` reads and VCS-tag parsing) when the completion opens, cache it on
  the widget for the active completion session, and on each keystroke **filter the cached snapshot in memory** — **no
  disk I/O on the refresh/keystroke path** (tui_perf rule #7). Invalidate on close.
- Snapshotting at open also makes the menu stable while the user types (the list doesn't churn mid-selection as agents
  change state) — both faster and more intuitive.
- Snippet reads are already mtime-cached and only happen at open for the (~handful to ~dozens of) visible agents.
  Contingency: if profiling a very large visible set shows the open is heavy, move snippet building off-thread
  (`asyncio.to_thread`) and populate rows on completion — but the in-memory-filter design already keeps the hot
  keystroke path clean (respecting the typing activity gate, rule #9).

## Scope decisions

**Offered (v1):**

- All **named**, currently-visible agents (per `visible_agents()` of the focused Agents panel), in on-screen order.
- Inline completion for `%wait` (colon + paren, multi-value) and `#fork` (colon + paren, single-value), each with the
  status bullet + VCS badge + prompt snippet rows.
- Prefix match on the agent name (consistent with the rest of the directive/xprompt-arg completion family and compatible
  with shared-extension tab completion).

**Deliberately out of scope for v1 (documented follow-ups):**

- **Neovim / xprompt LSP** agent completion (see "Front-end scope").
- **Substring/fuzzy matching** on name/label/snippet (the wait modal uses substring; the inline path uses prefix today).
  Possible later enhancement; v1 stays prefix-on-name for consistency.
- **Filtering `#fork` to only resumable/`DONE` agents.** Semantically `#fork` resumes a _completed_ agent's chat, while
  `%wait` targets pending ones, so one could argue `#fork` should show only done agents. The request, however, says
  _"only (and all of) the agent names of agents that are currently visible"_ for both — so v1 honors that and shows the
  same visible set for both. Flagged here as an open question: if preferred, `#fork` could be narrowed to resumable
  agents. (Recommendation: keep them identical for v1 per the explicit spec; revisit if it feels noisy.)

## Testing

- **Shared provider (`agent_completion.py`):** from a fixed list of fake visible `Agent`s, candidates carry the correct
  canonical names, status, VCS workflow (parsed from a prompt with/without a tag), and a cleaned snippet; unnamed agents
  are skipped; duplicates de-duped; order preserved.
- **`%wait` token extraction:** colon and paren forms; active comma-fragment isolation; agent-name tokens containing
  dots/hyphens; `%w` alias resolves to `wait`; `time=` fragment yields no agent candidates; regression assertions that
  `%effort:`/`%auto:`/`%model:` boundaries are unchanged.
- **`%wait` candidate build + accept:** prefix filter; acceptance replaces only the active fragment, leaving earlier
  names intact.
- **`#fork` xprompt-arg:** `type: agent` classifies `#fork:`/`#fork(` as the agent kind and returns the shared
  candidates; prefix filter; acceptance replaces the value token; `type: agent` coerces like `word` at runtime.
- **Rendering:** unit-test the shared row builder (badge + snippet + status present and styled); refresh PNG snapshots
  if the visual suite covers the completion panel.
- **Gating:** menu respects `auto_directive_menu` (wait) and the existing xprompt-arg gate (fork); closes when the
  cursor leaves the argument region.

## Documentation / housekeeping

- Update the ACE `?` help popup to mention `%wait` / `#fork` agent-name completion (per the ace help-popup-sync
  convention in `src/sase/ace/AGENTS.md`).
- Add a glossary note (`memory/glossary.md`) describing inline agent-name completion for `%wait` and `#fork` sourced
  from the visible Agents-tab list, with the VCS-workflow badge and prompt snippet (memory edit included under this
  plan's approval).
- No CLI option changes; no `default_config.yml` changes (existing gating reused).

## Suggested phasing (each independently shippable)

1. **Shared provider:** `agent_completion.py` + VCS badge helper; refactor the wait modal/action to consume it; tests.
2. **`%wait` inline completion:** directive-aware comma-segmented token boundary + `wait` candidate branch + source live
   agents at open/refresh (snapshot+in-memory-filter) + shared row renderer; tests + help/glossary.
3. **`#fork` inline completion:** `type: agent` kind + `fork.yml` change + route to shared builder; tests.

## Files expected to change (Python TUI only — no Rust)

- `src/sase/ace/tui/agent_completion.py` _(new)_ — shared candidate provider + VCS workflow badge helper.
- `src/sase/ace/tui/actions/agents/_wait_resume.py` — refactor onto the shared provider; expose the public app-level
  `visible_agent_completion_candidates()` accessor.
- `src/sase/ace/tui/modals/wait_modal.py` — consume the shared candidate (optional badge adoption).
- `src/sase/ace/tui/widgets/directive_completion.py` — `wait` candidate branch + directive-aware, comma-segmented token
  boundary (colon + paren).
- `src/sase/ace/tui/widgets/xprompt_arg_assist.py` — `agent` input type → `xprompt_arg_agent` kind.
- `src/sase/ace/tui/widgets/_file_completion_xprompt_args.py` — route `xprompt_arg_agent` to the shared builder.
- `src/sase/ace/tui/widgets/_file_completion_open.py` / `_file_completion_refresh.py` — snapshot live agents at open,
  pass to the builders, filter cached snapshot on refresh.
- `src/sase/ace/tui/widgets/_prompt_input_bar_completion.py` — shared `_append_agent_completion_row()` + panel titles.
- `src/sase/ace/tui/widgets/_file_completion_accept.py` — ensure the agent kinds replace the active token/fragment span.
- `src/sase/xprompts/fork.yml` — `name.type: word` → `agent`.
- ACE `?` help popup source; `memory/glossary.md`.
- Tests under `tests/` for the provider, `%wait` extraction/build/accept, `#fork` type routing, rendering, and gating;
  PNG snapshots if applicable.

## Out of scope (possible follow-ups)

- Neovim / xprompt LSP agent completion (would need a live on-disk agent index and a separate "what is an agent here"
  decision; explicitly not "visible-on-the-tab").
- Substring/fuzzy matching across name/label/snippet.
- Narrowing `#fork` to only resumable/`DONE` agents.
- `%wait` `time=` value completion (durations/absolute times) — orthogonal to agent names.
