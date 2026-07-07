---
create_time: 2026-07-07 15:35:46
bead_id: sase-5i
tier: epic
status: done
prompt: sdd/prompts/202607/vcs_ref_colon_completion.md
---
# Plan: VCS-Agnostic Ref Completion for `#gh:` / `#git:` (the `:` trigger)

## Problem & Product Context

The `sase-5h` epic taught sase to complete the _second_ half of a VCS ref: typing `/` inside `#gh:bbugyi200/` opens a
live repo menu. But the _first_ half is still a memory test. Typing `#gh:` or `#git:` today shows only the
candidate-less xprompt argument hint — the user must remember project names, active ChangeSpec names, and GitHub owner
spellings unaided, even though sase already knows all three. We even solved this exact problem _cross-provider_ with the
`#+` menu (epic `sase-4z`); this plan brings the same data to the provider-scoped moment where the user has already
committed to a VCS type: **when the user types `:` (or `(`) after a VCS workflow tag, open a completion menu listing
every ref that tag can accept** — active projects, active ChangeSpecs, and (for providers that have them) organizations
— in both frontends:

1. The `sase ace` TUI prompt input widget.
2. Editors via the Rust `sase-xprompt-lsp` server — `sase-nvim` inherits passively (`:` and `(` are **already**
   advertised trigger characters in `server.rs`; assert, don't add).

And it must be **VCS-agnostic**: a future `sase-gitlab` plugin (which we may never see) gets projects and ChangeSpecs in
its `#gl:` menu _for free_ (they come from sase's own project records), and lights up group completion by implementing
one optional hook. Providers without a namespace concept (bare `#git`, `#cd`) simply never implement it.

### UX walkthrough (the product spec)

- User types `#gh` — existing behavior unchanged.
- User types `:` — the ref completion menu opens instantly (all data is local; no network, no loading states). The panel
  border title names the provider and what's listed, e.g. `GitHub · projects & PRs & orgs`; for `#git:` it reads
  `Bare Git · projects & PRs` (the orgs segment appears only when the provider returned namespaces).
- The menu lists, in order, each row visually typed by a colored badge (kinds must be unmistakable at a glance):
  1. **Projects** — `[P]` badge (the exact badge style the `#+` menu already uses: bold `#87D7FF`), project display
     name, dim provider/description column.
  2. **ChangeSpecs** — `[PR]` badge (bold `#00D7AF`, as in `#+`), ChangeSpec name, dim status + owning-project column.
  3. **Organizations** — a new namespace badge in a third color that clashes with neither (e.g. bold `#FFAF5F`), with
     provider-supplied badge text (default `org`; a GitLab-style plugin could say `group`). The label renders with a
     trailing slash — `sase-org/` — signalling "this drills down". The dim column shows the plugin-supplied description
     (e.g. `2 active projects` or `from github_orgs`).
- On this machine, `#gh:` shows the `gh_*` projects and their active PRs, plus orgs `bbugyi200` and `sase-org` (derived
  from active `gh_<owner>__<repo>` project records, unioned with the `github_orgs` config — both sources agree here).
  `#git:` shows only bare-git projects/PRs — no org section, because the bare-git provider has no namespace concept.
- Typing narrows the menu with case-insensitive **prefix** matching on names and project aliases (the `#+` rule).
  `#gh:sa` keeps project `sase` and org `sase-org/`; deleting back past `:` dismisses.
- **Accepting a project or ChangeSpec** performs a token-local edit with the sase-5h semantics: `#gh:` → `#gh:sase `
  (trailing space appended when not already followed by whitespace); paren form `#gh(sase` → `#gh(sase)`, closing the
  paren if unclosed. Cursor lands after the suffix, ready to keep typing the prompt.
- **Accepting an organization chains**: `#gh:` → `#gh:sase-org/` with **no** trailing space/close-paren and the cursor
  right after the `/` — which is precisely the sase-5h repo-completion trigger, so the repo menu opens immediately (the
  TUI re-runs its auto-open path after the edit; the LSP item carries a best-effort
  `command: editor.action.triggerSuggest` for clients that honor it). Two keystrokes take the user from `#gh` to a live
  list of an org's repositories.
- Typing a character that makes the ref a non-candidate (`~`, `.`, or `/` at ref start — path-style refs; `://` — URLs)
  dismisses the menu and falls through to today's behavior. Once the ref contains a `/`, the sase-5h `vcs_repo` context
  owns the token; this feature owns only the root segment.
- **Auto-open is candidate-gated**: typing `:`/`(` auto-opens the menu only when at least one candidate exists for that
  workflow. This keeps `#cd:/tmp/foo` (a workflow whose refs are paths) and empty-catalog situations silent instead of
  flashing a useless placeholder. `Ctrl+T` force-opens anywhere inside a triggering ref and _does_ show the dim-italic
  "no known projects, PRs, or organizations" placeholder row, matching the `#+` empty-state pattern.
- In Neovim: typing `:` after `#gh` fires a standard LSP completion request; the identical items/edits arrive via
  `textEdit`s. Zero Lua changes.

### Why this is the right scope

This is the "Owner/namespace completion" future-work bullet from the sase-5h epic, grown to its natural product shape:
the ref root accepts three thing-kinds (`resolve_gh_ref` resolves `owner/repo` paths, project names/aliases, _and_
ChangeSpec names), so the menu should offer all three, reusing the `#+` catalog for the first two rather than inventing
a second source of truth.

## Design Principles

1. **VCS-agnostic by construction.** Core (Python + Rust) learns only: "the cursor is in the root segment of a
   registered VCS workflow ref → offer that workflow's project/ChangeSpec entries plus whatever namespaces its plugin
   volunteers." Project/ChangeSpec data comes from sase's own records (`build_vcs_project_completion_entries`, filtered
   by `vcs_prefix`); namespaces come from one new optional hook. No provider semantics in core, ever.
2. **Local data only — no network, no async.** Every candidate source is a local read that sase already performs and
   caches for the `#+` menu. The new hook's contract explicitly requires fast, local-only work (derive from project
   records/config; never call the network) because it sits behind an interactive keystroke. This keeps the TUI path
   synchronous (per `memory/tui_perf.md`) and means the LSP needs **no helper-bridge subprocess** for this feature.
3. **One catalog, three consumers.** The materialized `vcs_project_catalog.json` (already written at LSP launch and
   already carrying `workflow_names` + full entries with `vcs_prefix`/`kind`/`status`) grows a `namespaces` section. The
   TUI, the Rust builder, and the LSP all see byte-identical candidate data, and `#gh:` freshness is _identical_ to `#+`
   freshness by construction — same file, same warming, same refresh.
4. **Cross-language parity contract.** Trigger detection and the accept transform (including the org-chaining variant)
   are implemented identically in Python (`sase`) and Rust (`sase-core`), pinned by a shared golden-vector table —
   exactly like `VCS_REPO_GOLDEN_VECTORS`.
5. **Precedence is explicit and tested.** Within a VCS token: ref-with-`/` → `vcs_repo` (sase-5h); ref-without-`/` →
   `vcs_ref` (this plan); no match → xprompt-argument hint and all other existing behavior, byte-for-byte unchanged.
6. **Degrade to empty, never to broken.** Unknown tag, empty catalog, hook exception, malformed catalog file — every
   failure yields either silence (no auto-open), a helpful placeholder (explicit open), or an empty LSP list.

## Architecture Overview

```
                      ┌─────────────────────────────────────────────────┐
                      │ sase-github (plugin)                            │
                      │ ws_list_ref_namespaces("gh")                    │
                      │ → owners of active gh_<owner>__<repo> records   │
                      │   ∪ github_orgs config   (local reads only)     │
                      └───────────────▲─────────────────────────────────┘
                                      │ pluggy (sase_workspace, firstresult)
┌──────────────────┐   ┌──────────────┴─────────────────────────────────┐
│ TUI (sase ace)   │──▶│ sase core headless module                      │
│ sync, warmed     │   │ xprompt/vcs_ref_completion.py                  │
└──────────────────┘   │ trigger detect · candidate assembly (reuses    │
                       │ vcs_project entries by prefix) · accept        │
┌──────────────────┐   │ transform · golden vectors                     │
│ sase-xprompt-lsp │   └──────────────▲─────────────────────────────────┘
│ (Rust; nvim)     │                  │ vcs_project_catalog.json (v3:
│ in-memory catalog│──── reads ───────┘ entries + workflow_names +
│ pure classify/   │                    namespaces) — no bridge call
│ edit in core     │
└──────────────────┘
```

## Detailed Design

### 1. Trigger detection (parity-locked, both languages)

New context kind **`vcs_ref`** (Rust: `CompletionContextKind::VcsRef`) in `src/sase/xprompt/vcs_ref_completion.py` /
`sase_core::editor`. Detection is the exact complement of `find_vcs_repo_trigger` within the same token grammar:

- Token: `#<name><hitl?><sep><ref…>` at BOF / start-of-line / after whitespace, `<name>` a registered workflow name
  (Python: `get_workflow_names()`; Rust: the catalog's `workflow_names`), `<hitl>` ∈
  {``, `!!`, `??`}, `<sep>` ∈ {`:`, `(`}. (The legacy `_` separator stays unsupported, per the sase-5h decision.)
- Cursor inside the ref span; ref text before the cursor contains **no** `/` (a `/` hands the token to `vcs_repo`).
- Negatives: ref starting with `~`, `.`, or `/` (path-style refs — the `#cd:/tmp` case); `://` anywhere in the full ref
  (URLs); a `)` between separator and cursor (closed paren form). An **empty ref** (`#gh:` with the cursor right after
  the separator) is the canonical positive.
- `query` = ref text from the separator to the cursor. The trigger carries the same span fields as `VcsRepoTrigger`
  (token span, ref value span, query span) so the accept transform is token-local.

Dispatcher ordering, both sides: `vcs_repo` → **`vcs_ref`** → xprompt-argument detection → everything else. (The two new
kinds are disjoint by the `/` rule, but keeping repo first preserves sase-5h's tested order.) Python: the `_try_*` chain
in the TUI mixins; Rust: `classify_completion_context_with_workflows` in `crates/sase_core/src/editor/completion.rs`.

### 2. The plugin hook (the VCS-agnostic seam)

New **optional** hookspec on the existing `sase_workspace` group (`src/sase/workspace_provider/_hookspec.py`),
`firstresult=True`, same claim pattern as `ws_list_repo_candidates` (return `None` unless you own the workflow type):

```python
def ws_list_ref_namespaces(self, workflow_type: str) -> VcsRefNamespaces | None:
    """List org/group-style namespace candidates for a workflow's ref root.

    Must be fast and local-only (project records, config) — it runs on the
    interactive completion path. Never perform network or subprocess work.
    """
```

- `VcsNamespaceEntry`: `name` (e.g. `"sase-org"`), `description` (dim column text, e.g. `"2 active projects"`),
  `kind_label` (badge text, default `"org"`).
- `VcsRefNamespaces`: `entries: tuple[VcsNamespaceEntry, ...]` (+ room for future fields). No error channel — this is
  local-only; plugin failures are caught by the registry wrapper and treated as "no namespaces".
- Public wrapper `list_ref_namespaces(workflow_type)` in `workspace_provider/_registry.py`, exported from
  `workspace_provider/__init__.py`, returning an empty result when no plugin claims the type.

This hook is the _only_ thing a provider must implement to add its namespace kind; projects and ChangeSpecs require
nothing from plugins at all.

### 3. Headless foundations (`src/sase/xprompt/vcs_ref_completion.py`)

A sibling of `vcs_repo_completion.py`, but simpler (no fetch/TTL machinery — everything is local):

- `find_vcs_ref_trigger(prompt, cursor, workflow_names)` — the Python half of the parity contract (section 1).
- `apply_vcs_ref_selection(prompt, trigger, selected_ref, *, chain=False)` — the canonical token-local accept transform.
  Terminal form (`chain=False`): replace the ref value span, append a trailing space (colon form, unless already
  followed by whitespace) or close an unclosed paren — byte-compatible with `apply_vcs_repo_selection`. Chaining form
  (`chain=True`, org rows): insert `selected_ref` ending in `/`, **no** suffix in either separator form, documented
  cursor position immediately after the `/`. `VCS_REF_GOLDEN_VECTORS` (same `<CURSOR>`-marker format as sase-5h) pins
  both forms across colon/paren/HITL/BOF/mid-prompt cases plus all negatives.
- `build_vcs_ref_candidates(workflow)` — candidate assembly: `build_vcs_project_completion_entries()` (the existing
  mtime-signature-cached `#+` catalog) filtered to `vcs_prefix == workflow`, plus `list_ref_namespaces(workflow)` behind
  a small module-level cache keyed by the same projects-dir signature (so the hook is not re-invoked per keystroke).
  Returns the ordered kinds: projects, ChangeSpecs, namespaces.
- `filter_vcs_ref_candidates(candidates, query)` — case-insensitive prefix matching on entry name or project alias
  (delegating to `filter_vcs_project_entries` for entry rows) and on namespace name; preserves kind grouping.
- Extend `vcs_project_catalog_payload()` with a `namespaces` key — `{workflow: [{name, description, kind_label}, …]}`
  built by invoking the hook once per registered workflow name — and bump `VCS_PROJECT_CATALOG_SCHEMA_VERSION` to 3.
  Materialization (`sase.integrations.xprompt_lsp`) is untouched; the Rust loader accepts v2 **and** v3, defaulting
  `namespaces` to empty, so mixed-version skew degrades gracefully (old binary + new catalog tolerates the extra key it
  already ignores; new binary + old catalog completes without orgs).

### 4. sase-github implementation

- `ws_list_ref_namespaces` claims only `workflow_type == "gh"`. Candidates = owners parsed from active project records
  whose storage name matches the canonical `gh_<owner>__<repo>` shape (reusing `_canonical_project_name_base`'s format,
  records via the existing `_list_project_records` helper restricted to the active lifecycle state), unioned with
  `get_github_orgs()` from config. Deduped case-insensitively (first spelling wins), name-sorted. Descriptions:
  `"N active project(s)"` for record-derived owners, `"from github_orgs"` for config-only ones; `kind_label="org"`.
- Local reads only — no `gh` subprocess, honoring the hook contract. (A live `gh org list` source is explicit future
  work.)

### 5. TUI integration (new completion kind `vcs_ref`)

Follows the established wiring shape through the completion mixin stack (`_file_completion_*.py`,
`_prompt_input_bar_completion.py`, `_prompt_text_area_key_handling.py`); the implementing agent must read
`memory/tui_perf.md` first (this touches the key-handling hot path — and `:` is a far more common keystroke than `/`, so
the detector's cheap-bail-out path matters):

- **Auto-open** when a typed `:` or `(` completes the trigger (the same after-insert pattern the `+` and `/` characters
  use in `_prompt_text_area_key_handling.py`), gated on at least one candidate existing for that workflow; `Ctrl+T`
  force-opens (placeholder row allowed) via the existing precedence-gated `_try_*` chain, slotted after `vcs_repo`.
- **Candidates** load synchronously from `build_vcs_ref_candidates` — the project catalog is already warmed at
  prompt-bar activation by `_warm_vcs_project_completion_catalog`; extend that warmer to also prime the namespaces cache
  so the first `:` renders instantly.
- **Refresh/narrowing** re-runs the detector and re-filters locally per keystroke; typing `/` hands off cleanly to the
  `vcs_repo` menu; negatives dismiss.
- **Accept** applies `apply_vcs_ref_selection` as a token-local buffer edit (the repo-menu accept shape — _not_ the `#+`
  whole-prompt rewrite; the user typed this tag deliberately, so we complete in place). After an org (chaining) accept,
  explicitly invoke the repo-menu open path so the chained menu appears without an extra keystroke.
- **Rendering**: new `_append_vcs_ref_completion_row` dispatched by candidate `metadata` `isinstance`, per the
  established pattern — reusing the `[P]`/`[PR]` badge styles and column-width helpers, adding the namespace badge
  (uppercased `kind_label`, trailing-slash label). Border title `provider_display · projects & PRs[& orgs]`. Standard
  `MAX_VISIBLE`/overflow handling.
- New candidate metadata types: entry rows reuse `VcsProjectEntry`; org rows use `VcsNamespaceEntry`; placeholder uses
  `metadata=None` (non-selectable), all consistent with existing dispatch.

### 6. Rust core (`sase-core`: crates/sase_core/src/editor/)

- `CompletionContextKind::VcsRef` in `wire.rs`; wire structs for namespace entries; catalog deserialization accepts
  schema v2/v3 with `namespaces` defaulting empty.
- `detect_vcs_ref_context_at_position(...)` in `completion.rs`/`token.rs` (taking `known_workflow_names`), slotted into
  `classify_completion_context_with_workflows` **after** the VcsRepo check and **before** xprompt-argument detection,
  with explicit ordering tests (`#gh:owner/` → VcsRepo; `#gh:` / `#gh:sa` → VcsRef; `#gh:~/x`, `#foo:x`, `#gh:123)` →
  today's behavior).
- `build_vcs_ref_completion_candidates(entries, namespaces, context)` — pure function producing token-local
  `EditorTextEdit`s: terminal edits for project/ChangeSpec rows, chaining (`owner/`, no suffix) edits for namespace
  rows. Alias-aware matching mirrors the existing VcsProject candidate path.
- Rust golden-vector table byte-identical to Python's `VCS_REF_GOLDEN_VECTORS`, both suites failing on drift.

### 7. LSP wiring (`sase-core`: crates/sase_xprompt_lsp/)

- New dispatch branch in `server.rs` for `VcsRef` contexts, served **entirely from the in-memory materialized catalog**
  — no host-bridge call, no spawn_blocking, no timeout machinery. This is the payoff of principle 2.
- Completion items: `label` = name (orgs labeled `name/`), `kind` distinguishing the three row types (e.g. Module /
  Reference / Folder), `detail` = provider + kind + status/owning-project or namespace description, `filterText` = name,
  `sortText` encoding group order (projects < PRs < orgs) then name, `textEdit` from the core builder. Org items
  additionally carry `command: editor.action.triggerSuggest` (best-effort chaining; harmless when ignored).
- Assert `:` and `(` remain in the advertised `triggerCharacters` — they are already present; do not add.
- Tests: classification/completion over a canned v3 catalog; v2-catalog fallback (no org items, no errors); ordering and
  `#gh:owner/`-still-VcsRepo regression; malformed-namespaces degradation.

### 8. Neovim (sase-nvim)

Zero functional Lua changes. Verification + docs only: `tests/lsp_vcs_ref_smoke.lua` cloned from the sase-5h smoke test
(offline — point the LSP at a canned v3 catalog file via the existing `SASE_XPROMPT_VCS_PROJECT_CATALOG` env var; no
bridge stub needed since this feature makes no bridge calls): assert `:` is an advertised trigger character, drive
`textDocument/completion` inside `#gh:`, apply a project `textEdit` and an org `textEdit`, assert the canonical
expansions. Plus the README completion-table row.

### 9. Configuration

Minimal, mirroring sase-5h (update `src/sase/default_config.yml` **and** `src/sase/config/sase.schema.json`, per
`memory/gotchas`): a `vcs_ref_completion` section with `enabled: true` only — no TTL/limit knobs, because there is no
fetch. Disabling turns off detection in the TUI and omits `namespaces` from (and stops `vcs_ref` classification via) the
materialized catalog.

## Phases

Each phase is a self-contained unit for one agent instance. Linked-repo phases must open their repo with
`sase workspace open -p <repo> -r "<reason>" <workspace_num>` (using the workspace number of the primary sase repo
checkout they are started in) and run that repo's own checks.

### Phase 1 — Contracts + Python headless foundations (repo: `sase`)

The keystone phase; everything else depends on it.

- `ws_list_ref_namespaces` hookspec + `VcsNamespaceEntry`/`VcsRefNamespaces` dataclasses + registry wrapper/export with
  exception-safe "no namespaces" fallback.
- `src/sase/xprompt/vcs_ref_completion.py`: trigger detection, accept transform (terminal + chaining), candidate
  assembly + signature-keyed namespace cache, filtering, and the **golden-vector table** (the parity contract Phase 4
  mirrors).
- `vcs_project_catalog_payload()` v3 (`namespaces` key, schema bump); config plumbing (`default_config.yml`,
  `sase.schema.json`, loader).
- Tests: golden vectors; trigger positive/negative suites (empty ref, partial query, colon/paren/HITL, BOF/mid-prompt,
  `~`/`.`/`/`-start, `://`, closed-paren, unknown-tag, slash-hands-off-to-repo); assembly filtering by `vcs_prefix`;
  namespace-cache invalidation; hook-exception fallback; payload v3 shape. Verification: `just install`, `just check`.

### Phase 2 — GitHub provider implementation (repo: `sase-github`; depends on Phase 1)

- `ws_list_ref_namespaces` per section 4 (record-derived owners ∪ `github_orgs`, dedupe, descriptions, ownership claim
  `None` for `workflow_type != "gh"`).
- Tests with faked project records/config: owner parsing from canonical names (incl. names that don't match the
  `gh_*__*` shape → skipped), config union + case-insensitive dedupe, active-only lifecycle filtering, no
  subprocess/network use. Docs: plugin README note. Verification: this repo's own just/test targets.

### Phase 3 — TUI menu (repo: `sase`; depends on Phase 1)

- New `vcs_ref` completion kind wired through the mixin stack per section 5: candidate-gated auto-open on `:`/`(`,
  Ctrl+T with placeholder, narrowing, dismissal, token-local accept, org-accept chaining into the repo menu, warmer
  extension. **Read `memory/tui_perf.md` first.**
- Rendering: row appender with the three badge types, border title, overflow.
- Tests: widget tests for open/narrow/accept(project, PR, org-chain)/dismiss/hand-off-to-repo-menu; ordering tests
  against the `vcs_repo` and xprompt-arg paths; PNG snapshots for populated (all three kinds), no-orgs (`#git:`), and
  placeholder menus (`just test-visual`). Verification: `just install`, `just check`. Manual: `sase ace`, type `#gh:`
  and `#git:`.

### Phase 4 — Rust core: context kind + detector + builder + vectors (repo: `sase-core`; depends on Phase 1)

- `CompletionContextKind::VcsRef`, namespace wire structs, v2/v3 catalog tolerance, detector with precedence, pure
  candidate/edit builder (terminal + chaining), golden-vector table mirroring Phase 1 byte-for-byte.
- Unit tests: classification ordering matrix, token spans, golden vectors, v2-catalog default. Verification:
  `cargo fmt --check`, `cargo test -p sase_core`.

### Phase 5 — LSP wiring (repo: `sase-core`; depends on Phase 4)

- `server.rs` VcsRef dispatch from the in-memory catalog; item conversion (`kind`/`detail`/`filterText`/`sortText`/
  `textEdit`, org `command`); trigger-character assertions.
- Tests per section 7. Verification: `cargo fmt --check`, `cargo test -p sase_xprompt_lsp` (and `-p sase_core`).

### Phase 6 — Neovim smoke test, end-to-end verification, docs (repos: `sase-nvim`, `sase`; depends on Phases 2, 3, 5)

- `tests/lsp_vcs_ref_smoke.lua` (canned catalog, offline) + README completion-table row in sase-nvim.
- Main-repo docs: user-facing completion docs section; CHANGELOG entry; **glossary Tier-1 memory entry** ("VCS Ref
  Completion") — a Tier-1 memory edit, authorized only by the user's approval of this plan.
- End-to-end manual verification: TUI with the real sase-github plugin (`#gh:` → projects/PRs/orgs incl. `bbugyi200` and
  `sase-org`; org accept chains into live repo menu; accepted refs launch-resolve), `#git:` (projects/PRs only); Neovim
  against a freshly built sibling LSP binary (`SASE_XPROMPT_LSP_CMD`) verifying menu, narrowing, both accept forms, and
  that `#+`, `#gh:owner/`, `#foo:`/`#foo(...)` xprompt completions are unaffected.
- Verification: nvim smoke suite headless; `just install && just check` in sase if any main-repo files changed.

## Risks & Mitigations

- **Parity drift (Python ↔ Rust).** One golden-vector table defined in Phase 1, mirrored byte-identically in Phase 4;
  both suites fail on drift (the proven sase-4z/5h mitigation).
- **Shadowing existing behavior on a very common keystroke (`:`).** The detector is narrow (registered workflow names
  only, token-anchored, path/URL negatives) with a cheap bail-out (token must start with `#`), and both dispatchers get
  explicit ordering-matrix tests. `#gh:owner/` (repo menu), `#+` (project menu), `#foo:` (xprompts), and plain prose
  colons are all pinned unchanged.
- **A future plugin does slow/network work in the namespaces hook.** Contract documented on the hookspec; registry
  wrapper is exception-safe; core additionally memoizes per projects-dir signature so even a slow hook fires rarely. (If
  a provider ever genuinely needs remote namespaces, that's the moment to add an async/bridge path — explicitly out of
  scope now.)
- **Catalog schema skew (v2 ↔ v3) across sase / LSP binary versions.** Rust accepts both versions (`namespaces` defaults
  empty); the v3 payload only adds a key, which the v2 loader already tolerates. Worst case is orgs missing from the
  editor until the dev-update flow rebuilds the LSP — never a broken menu.
- **Org list surprises** (user expects an org that has no active project and isn't in `github_orgs`). The two sources
  are deterministic and documented; the description column says where each org came from. MRU/live owner discovery is
  listed future work.
- **Auto-open annoyance in colon-heavy prompts.** Auto-open requires a registered workflow tag immediately before the
  separator _and_ a non-empty candidate set; prose like `note: fix this` can never match (`note` is not a workflow).

## Out of Scope / Future Work

- Live/remote namespace discovery (`gh org list`, MRU owners) and any async namespace fetching.
- Repo-completion changes (sase-5h behavior is untouched beyond dispatcher ordering).
- The legacy `_` ref separator; fuzzy (non-prefix) matching; `#+` menu changes.
- A GitLab/other-VCS plugin itself — this plan guarantees and documents the seam (`ws_list_ref_namespaces` + automatic
  project/ChangeSpec rows).
- Completing ChangeSpecs of _other_ providers under a mismatched tag (each tag shows only its own workflow's refs).
