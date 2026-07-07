---
create_time: 2026-07-07 13:10:16
bead_id: sase-5h
tier: epic
status: done
prompt: sdd/prompts/202607/vcs_repo_slash_completion.md
---
# Plan: VCS-Agnostic Repo Completion for `#gh` Refs (the `/` trigger)

## Problem & Product Context

Typing a `#gh` ref today is a memory test. `#gh:bbugyi200/` is a syntactically valid partial ref (the ref grammar
`[a-zA-Z0-9_./-]+` already allows `/`), but nothing completes it — the user must remember the exact repo name or leave
the TUI to look it up. We already solved the analogous problem for _projects_ with the `#+` VCS Project Completion
feature (epic `sase-4z`); this plan extends the same product idea one level deeper: **when the user types `/` inside a
`#gh` ref (e.g. `#gh:bbugyi200/`), open a completion menu listing that owner's GitHub repositories**, fetched live from
GitHub and rendered beautifully in both frontends:

1. The `sase ace` TUI prompt input widget.
2. Editors via the Rust `sase-xprompt-lsp` server — which `sase-nvim` inherits passively (no Lua changes needed, since
   trigger characters and edits flow from the server).

And it must be **VCS-agnostic**: GitHub is just the first provider. A future `sase-gitlab` plugin must be able to light
up the identical completion for `#gl:group/subgroup/` by implementing one hook — with zero changes to sase core, the
Rust core, the LSP, or sase-nvim.

### UX walkthrough (the product spec)

- User types `#gh:bbugyi200` — existing behavior unchanged (the xprompt arg hint from `gh.yml` still shows).
- User types `/` — the repo completion menu opens immediately. If this owner's repo list is cached and fresh, repos
  appear instantly; otherwise the menu shows a dim italic _"fetching bbugyi200/ repositories…"_ row while a background
  fetch runs, then fills in (the menu never blocks a keystroke).
- Menu rows show: the repo name (bold), a dim truncated description, and status badges — `[private]`, `[fork]`,
  `[archived]` — in the same badge style as the `#+` menu's `[P]`/`[PR]` badges. The panel border title identifies the
  provider and namespace, e.g. `GitHub · bbugyi200/`. Rows are capped at the existing `MAX_VISIBLE = 10` with the
  standard `↓ N more…` overflow line.
- Typing `#gh:bbugyi200/sa` narrows the menu (local filtering — no new network call per keystroke).
- Accepting a row performs a **token-local edit**: `#gh:bbugyi200/` → `#gh:bbugyi200/sase ` (trailing space appended so
  the user keeps typing their prompt). Paren form completes to `#gh(bbugyi200/sase)`, closing the paren if unclosed.
- Failure states are first-class UI, not silence: _"no repositories found for bbugyi200"_ (empty), _"repo listing failed
  — run `gh auth login`"_ (auth error), _"repo listing failed — network error"_ (offline; stale cached results are
  served instead when available).
- In Neovim: typing `/` inside `#gh:bbugyi200/` fires an LSP completion request (`/` is **already** an advertised
  trigger character in `server.rs`), and the identical menu/edit behavior arrives via standard LSP completion items.

### Ranking (what makes it feel smart)

Within the fetched list: candidates whose name starts with the typed query rank first; within each group, sort by
`pushed_at` descending (most recently active repos first), missing timestamps last, then name ascending. With an empty
query this means the owner's most active repos are on top — usually exactly what the user wants. Filtering/ranking is
presentation-layer only (each frontend may filter; the LSP additionally relies on client-side `filterText` matching) —
only the **accept transform** is parity-locked (see below).

## Design Principles

1. **VCS-agnostic by construction.** Sase core (Python + Rust) never learns GitHub semantics. It learns: "the token is a
   registered VCS workflow tag (`get_workflow_names()`), the ref contains a `/`, so ask the owning workspace plugin for
   repo candidates in namespace X." The namespace is _everything before the last `/`_ — one-level for GitHub,
   arbitrarily nested for GitLab groups — and the plugin decides what a namespace means.
2. **Never do network or disk-heavy work on the keystroke path** (per `memory/tui_perf.md`). All fetching is
   asynchronous (TUI background worker; LSP subprocess bridge with timeout) in front of a shared TTL cache.
3. **One Python fetch/cache implementation, two consumers.** The TUI calls it in-process; the Rust LSP calls it via the
   existing helper-bridge subprocess mechanism (`sase editor helper-bridge <op>`, JSON over stdio) — the same primitive
   the LSP already uses for xprompt/snippet catalogs. No HTTP client or GitHub knowledge ever enters the Rust repo.
4. **Cross-language parity contract.** Trigger detection and the accept transform are implemented identically in Python
   (`sase`) and Rust (`sase-core`), enforced by a shared golden-vector table — exactly like
   `apply_vcs_project_selection` for the `#+` feature.
5. **Degrade to empty, never to broken.** Every failure (no plugin owns the tag, `gh` missing, unauthenticated, rate
   limited, offline) produces either a helpful placeholder row (TUI) or an empty completion list (LSP), never an error
   dialog or a hung request.

## Architecture Overview

```
                       ┌──────────────────────────────────────────────┐
                       │  sase-github (plugin)                        │
                       │  ws_list_repo_candidates("gh", "bbugyi200")  │
                       │  → `gh repo list` subprocess (auth: gh CLI)  │
                       └──────────────▲───────────────────────────────┘
                                      │ pluggy (sase_workspace group, firstresult)
┌──────────────────┐   ┌──────────────┴───────────────────────────────┐
│ TUI (sase ace)   │──▶│  sase core headless module                   │
│ background worker│   │  xprompt/vcs_repo_completion.py              │
└──────────────────┘   │  trigger detect · fetch orchestration ·      │
                       │  on-disk TTL cache (per workflow+namespace)  │
┌──────────────────┐   └──────────────▲───────────────────────────────┘
│ sase-xprompt-lsp │  subprocess:     │
│ (Rust; nvim)     │──"sase editor helper-bridge vcs-repo-catalog"────┘
│ + in-mem TTL     │
│ + pure classify/ │   (classification & accept-edit logic: Rust
│   edit in core   │    sase_core::editor, golden-vector parity)
└──────────────────┘
```

## Detailed Design

### 1. Trigger detection (parity-locked, both languages)

New context kind **`vcs_repo`** (Rust: `CompletionContextKind::VcsRepo`). Detection rule:

- The token before/around the cursor is a VCS workflow tag: `#<name><hitl?><sep><ref…>` at BOF / start-of-line / after
  whitespace, where `<name>` is a **registered workflow name** (Python: `workspace_provider.get_workflow_names()`; Rust:
  a `known_workflow_names: &[String]` parameter — the LSP already has these via the `workflow_names` array in the
  materialized vcs-project catalog JSON), `<hitl>` ∈ {``, `!!`, `??`}, and `<sep>` ∈ {`:`, `(`}. (The legacy `#gh_ref`
  underscore form is intentionally not supported for completion.)
- The cursor sits inside the ref, and the ref text before the cursor contains at least one `/`.
- `namespace` = ref text from the separator up to the **last** `/` before the cursor; `query` = text after that `/` up
  to the cursor. An empty namespace (`#gh:/`), a namespace starting with `~` or `.` (path-style refs), or a ref
  containing `://` (URLs in paren form) does **not** trigger.
- The detected context carries the byte spans needed for the accept edit: the full ref value span plus namespace/query
  subspans.

**Precedence is the one subtle part**: `#gh:` tokens are _currently_ claimed by the xprompt-argument assist path
(`gh.yml` is a real catalog entry whose `gh_ref` input has type `word`, which maps to the candidate-less
`xprompt_arg_type_hint` / `XpromptArgumentTypeHint` kind on both sides). The new `vcs_repo` detector must therefore run
**before** xprompt-argument detection in both dispatchers (Python `_try_*` chain in the TUI mixins; Rust
`classify_completion_context` in `crates/sase_core/src/editor/completion.rs`). When the vcs_repo rule does not match (no
`/` yet, unknown tag, path-style ref), everything falls through to today's behavior — including the existing `gh.yml`
argument hint.

### 2. The plugin hook (the VCS-agnostic seam)

New hookspec on the existing `sase_workspace` pluggy group (`src/sase/workspace_provider/_hookspec.py`),
`firstresult=True` — plugins return `None` unless they own the workflow type (same claim pattern as `ws_resolve_ref`):

```python
def ws_list_repo_candidates(workflow_type: str, namespace: str) -> VcsRepoCandidates | None:
    """List repository completion candidates for *namespace* (e.g. a GitHub owner/org)."""
```

- `VcsRepoCandidates`: `status` (`"ok"` | `"error"`), `error_kind` (`"auth"` | `"network"` | `"not_found"` |
  `"tool_missing"` | `"unsupported_namespace"` | `"unknown"` | `None`), `message` (human hint for the error row),
  `provider_display` (e.g. `"GitHub"`, for the menu title), `entries`.
- `VcsRepoEntry`: `name` (repo short name), `ref` (full insert text, `namespace/name`), `description`, `visibility`,
  `is_fork`, `is_archived`, `pushed_at` (ISO-8601 or `None`).
- Public wrapper `list_repo_candidates(workflow_type, namespace)` in `workspace_provider/_registry.py`, exported from
  `workspace_provider/__init__.py`.

This is the _only_ thing a future `sase-gitlab` must implement to get the whole feature, on every surface.

### 3. Headless foundations + shared cache (`src/sase/xprompt/vcs_repo_completion.py`)

A sibling of `vcs_project_completion.py`, structured the same way:

- `find_vcs_repo_trigger(prompt, cursor, workflow_names)` — the Python half of the parity contract.
- `apply_vcs_repo_selection(...)` — the canonical token-local accept transform (colon form appends a trailing space when
  not already followed by whitespace; paren form closes an unclosed paren). Golden-vector table pins it.
- `fetch_repo_candidates(workflow_type, namespace)` — fetch orchestration in front of the cache:
  - On-disk cache at `sase_subdir("vcs_repo_cache")/<workflow_type>/<namespace-slug>.json` (schema-versioned payload
    with `fetched_at`), fresh TTL ~10 minutes, plus an in-process memo. **Stale-if-error**: when a refresh fails, serve
    the stale payload (any age) and surface the error kind alongside it.
  - Calls `workspace_provider.list_repo_candidates(...)` on cache miss/stale.
- `filter_vcs_repo_entries(entries, query)` + the ranking described above (presentation-layer, not parity-locked).
- `vcs_repo_catalog_response(request)` — the helper-bridge response builder (schema-versioned), so the LSP and TUI
  consume byte-identical candidate data.

### 4. Helper-bridge operation (LSP ↔ Python)

New operation `vcs-repo-catalog` under `sase editor helper-bridge` (parser in `src/sase/main/parser_editor.py`, dispatch
in `src/sase/integrations/editor_helpers.py`): reads `{"schema_version": 1, "workflow": "gh", "namespace": "bbugyi200"}`
from stdin, writes `{"schema_version": 1, "status": ..., "error_kind": ..., "provider_display": ..., "entries": [...]}`
to stdout. It simply calls `fetch_repo_candidates`, so the LSP shares the TUI's on-disk cache for free. (This phase adds
a CLI subcommand → the implementing agent must first read `memory/cli_rules.md` via `/sase_memory_read`.)

### 5. sase-github implementation

The plugin stays true to its gh-CLI-only philosophy (it has no HTTP client and delegates all auth to `gh`):

- `ws_list_repo_candidates` claims only `workflow_type == "gh"`. A namespace containing `/` returns
  `unsupported_namespace` (GitHub has no nested orgs).
- Fetch via `gh repo list <owner> --json name,description,visibility,isArchived,isFork,pushedAt --limit <max>`
  (subprocess, short timeout). For GitHub Enterprise, pass the host through the `GH_HOST` environment variable using the
  existing `config.py` host helpers (`get_default_github_host()` et al.) so Enterprise owners complete too. With an
  authenticated `gh`, private repos the user can access appear alongside public ones (hence the `[private]` badge).
- Structured error mapping: `gh` binary missing → `tool_missing` (_"install the gh CLI"_); auth failure → `auth` (_"run
  `gh auth login`"_); unknown owner → `not_found`; anything else → `network`/`unknown` with a terse message.
- No caching in the plugin — the shared cache in sase core (section 3) already throttles; the hook is only invoked on
  cache miss/stale.

### 6. TUI integration (new completion kind `vcs_repo`)

Follows the `#+` menu's wiring shape through the completion mixin stack
(`src/sase/ace/tui/widgets/_file_completion_*.py`, `_prompt_input_bar_completion.py`,
`_prompt_text_area_key_handling.py`):

- **Auto-open** when a typed `/` completes the trigger (like `+` does for `#+`), gated by the same auto-menu setting
  pattern; `Ctrl+T` works anywhere inside a triggering ref.
- **Async candidates — the one genuinely new mechanism in the TUI.** No existing menu fetches candidates asynchronously.
  On open: consult the in-process/disk cache synchronously (cheap); on hit, render candidates immediately; on miss,
  render the _loading_ placeholder row and start a `run_worker(thread=True)` fetch (the same worker facility used by
  `_warm_vcs_project_completion_catalog`), with in-flight dedupe per (workflow, namespace). When the worker finishes,
  refresh the menu **only if** it is still active with the same trigger context; otherwise drop the result (the cache
  keeps it for next time).
- **Refresh/narrowing** re-runs the trigger detector and filters cached entries locally (no network per keystroke);
  deleting back past the `/` dismisses the menu and restores prior behavior.
- **Accept** applies `apply_vcs_repo_selection` (token-local edit; cursor after the inserted ref + spacing).
- **Rendering**: new `_append_vcs_repo_completion_row` + border title (`provider_display · namespace/`), badges,
  dim-italic loading/empty/error rows, standard overflow line. New candidate `metadata` type dispatched by `isinstance`,
  per the established pattern.
- The implementing agent must read `memory/tui_perf.md` first (this touches the key-handling hot path).

### 7. Rust core (`sase-core`: crates/sase_core/src/editor/)

- New `CompletionContextKind::VcsRepo` in `wire.rs`; new wire structs mirroring `VcsRepoEntry`/result.
- `detect_vcs_repo_context_at_position(...)` in `completion.rs`/`token.rs`, taking `known_workflow_names` — checked
  **before** xprompt-argument detection in `classify_completion_context` (see precedence note above; classification call
  sites gain a workflow-names argument, defaulting to empty for callers without catalog data, which cleanly disables the
  feature rather than misfiring).
- `build_vcs_repo_completion_candidates(entries, context)` — pure function, candidates in, `EditorTextEdit`s out. A
  single token-local edit (no `additionalTextEdits`), so the non-overlap machinery the `#+` feature needed does not
  apply.
- Rust golden-vector table `vcs_repo_golden_vectors` byte-identical to the Python `_GOLDEN_VECTORS` for this feature
  (colon/paren/HITL forms, BOF/mid-prompt, trailing-space and close-paren rules, all negative cases).

### 8. LSP wiring (`sase-core`: crates/sase_xprompt_lsp/ + host_bridge)

- Extend the `HelperHostBridge` trait (`crates/sase_core/src/host_bridge.rs`) with a parameterized
  `vcs_repo_catalog(workflow, namespace)` operation; `CommandHelperHostBridge` spawns
  `sase editor helper-bridge vcs-repo-catalog` writing the request JSON to stdin (the bridge's existing shape);
  `StaticHelperHostBridge` gains a canned-response variant for tests.
- New dispatch branch in `server.rs` for `VcsRepo` contexts: `spawn_blocking` + ~5s timeout around the bridge call (the
  `catalog_cache.rs` pattern), in front of a small in-memory TTL cache (~45s) keyed by (workflow, namespace) so
  per-keystroke requests within one completion session hit memory, not a subprocess. Failures degrade to an empty list,
  warn-once logging, per the existing catalog philosophy.
- Completion items: `label` = repo name, `detail`/`documentation` = description + badges, `filterText` =
  `namespace/name`, `sortText` encodes the ranking, `textEdit` from the core builder. `/` is already in the server's
  advertised `triggerCharacters` — assert, don't add. Workflow names for classification come from the already-loaded
  vcs-project catalog JSON.

### 9. Neovim (sase-nvim)

Zero functional Lua changes — trigger characters, edits, and items all flow from the server. Work here is verification +
docs: a new `tests/lsp_vcs_repo_smoke.lua` cloned from `tests/lsp_vcs_project_smoke.lua` that stubs the helper bridge
(point `SASE_MOBILE_HELPER_BRIDGE_COMMAND` at a tiny script returning fixed JSON) so the test stays offline: assert `/`
is an advertised trigger character, drive `textDocument/completion` inside `#gh:bbugyi200/`, apply the returned
`textEdit`, and assert the canonical expansion. Plus the README completion-table row.

### 10. Configuration

Minimal new config (remember `src/sase/default_config.yml` per `memory/gotchas`): a `vcs_repo_completion` section with
`enabled: true`, `cache_ttl_seconds: 600`, and `max_repos: 200` (the `--limit` passed to providers). Disabling turns off
detection in the TUI and makes the bridge op return empty — the LSP needs no setting of its own.

## Phases

Each phase is a self-contained unit for one agent instance. Linked-repo phases must open their repo with
`sase workspace open -p <repo> -r "<reason>" <workspace_num>` (using the workspace number of the primary sase repo
checkout they are started in) and run that repo's own checks.

### Phase 1 — Contracts + Python headless foundations (repo: `sase`)

The keystone phase: everything other phases depend on, all headless (no UI).

- `ws_list_repo_candidates` hookspec + `VcsRepoCandidates`/`VcsRepoEntry` dataclasses + registry wrapper/export
  (`src/sase/workspace_provider/`).
- `src/sase/xprompt/vcs_repo_completion.py`: trigger detection, accept transform, fetch orchestration + on-disk TTL
  cache (stale-if-error), filtering/ranking, bridge response builder. Define the **golden-vector table** here — it is
  the parity contract Phase 4 mirrors. Public contract objects include `VcsRepoCompletionConfig`, `VcsRepoTrigger`,
  `VcsRepoFetchResult`, and `load_vcs_repo_completion_config`.
- `vcs-repo-catalog` helper-bridge op (parser + handler). **Requires `/sase_memory_read` of `memory/cli_rules.md`.**
- Config plumbing (`default_config.yml` + reader).
- Tests: golden vectors; trigger positive/negative suites (colon/paren/HITL, `~`/URL/empty-namespace negatives,
  nested-namespace split); cache TTL/stale-if-error behavior (hook faked); bridge op stdin/stdout round-trip incl. error
  statuses. Verification: `just install`, `just check`.

### Phase 2 — GitHub provider implementation (repo: `sase-github`; depends on Phase 1)

- Implement `ws_list_repo_candidates` (gh CLI subprocess, `GH_HOST` for Enterprise, structured error mapping,
  `unsupported_namespace` for nested namespaces, `max_repos` limit).
- Tests with mocked subprocess: happy path field mapping (name/description/visibility/fork/archived/pushed_at), each
  error mapping, Enterprise host env, ownership claim (`None` for `workflow_type != "gh"`).
- Docs: plugin README/`docs/configuration.md` note on completion + auth requirement. Verification: this repo's own
  just/test targets. Manual: `gh` authed → hook returns real repos for a known owner.

### Phase 3 — TUI menu (repo: `sase`; depends on Phase 1)

- New `vcs_repo` completion kind wired through the mixin stack: auto-open on `/`, Ctrl+T, refresh/narrowing, dismiss,
  accept via the canonical transform.
- The async fetch worker + in-flight dedupe + loading/empty/error placeholder rows; **read `memory/tui_perf.md` first.**
- Rendering: row appender, badges, provider·namespace border title.
- Tests: widget tests for auto-open/narrow/accept/dismiss and for each async state (fake hook: instant-hit, delayed,
  error) including the "menu closed before fetch finished" race; PNG snapshots for populated/loading/error menus
  (`just test-visual`). Verification: `just install`, `just check`. Manual: `sase ace`, type `#gh:bbugyi200/` with a
  stub provider.

### Phase 4 — Rust core: context kind + detector + builder + vectors (repo: `sase-core`; depends on Phase 1)

- `CompletionContextKind::VcsRepo`, wire structs, detector with `known_workflow_names` parameter (precedence before
  xprompt-arg detection), pure candidate/edit builder, `vcs_repo_golden_vectors` mirroring Phase 1's table
  byte-for-byte.
- Unit tests: classification order (a `#gh:owner/` token classifies VcsRepo while `#gh:owner` still reaches the
  xprompt-arg path; unknown tags don't fire), token spans, golden vectors.
- Verification: `cargo fmt --check`, `cargo test -p sase_core`.

### Phase 5 — LSP wiring (repo: `sase-core`; depends on Phases 1 & 4)

- `HelperHostBridge::vcs_repo_catalog` (+ command/static impls), server dispatch branch with spawn_blocking + timeout +
  in-memory TTL cache, item conversion (`filterText`/`sortText`/`textEdit`), degrade-to-empty failure handling.
- Tests: server classification/completion tests with `StaticHelperHostBridge` canned responses; timeout and
  error-degradation tests; assert `/` remains in `triggerCharacters`.
- Verification: `cargo fmt --check`, `cargo test -p sase_xprompt_lsp` (and `-p sase_core`).

### Phase 6 — Neovim smoke test, end-to-end verification, docs (repos: `sase-nvim`, `sase`; depends on Phases 2, 3, 5)

- `tests/lsp_vcs_repo_smoke.lua` (stubbed bridge, offline) + README completion-table row in sase-nvim.
- Main-repo docs: user-facing completion docs page section; CHANGELOG entry; **glossary Tier-1 memory entry** ("VCS Repo
  Completion") — a Tier-1 memory edit, authorized by approval of this plan.
- End-to-end manual verification: TUI with the real sase-github plugin (`#gh:bbugyi200/` → live repos, accept, launch
  resolves); Neovim against a freshly built sibling LSP binary (`SASE_XPROMPT_LSP_CMD`), verifying menu, narrowing,
  acceptance, and that `#foo:`/`#foo(`/`#+` completions are unaffected.
- Verification: nvim smoke suite headless; `just install && just check` in sase if any main-repo files changed.

## Risks & Mitigations

- **Parity drift (Python ↔ Rust).** Same mitigation as `sase-4z`: one golden-vector table, defined in Phase 1, mirrored
  byte-identically in Phase 4; both suites fail on drift.
- **Shadowing the existing `#gh` arg hint / xprompt-arg completions.** The vcs_repo detector is deliberately narrow
  (registered workflow names only, `/` required, path/URL negatives) and both dispatchers get explicit ordering tests
  (`#gh:owner/` → vcs_repo; `#gh:owner`, `#foo:x/y` → unchanged behavior).
- **Network on the keystroke path / UI jank.** Structurally prevented: TUI consults only caches synchronously; fetches
  run in workers; the LSP wraps the bridge in a timeout + TTL cache and degrades to empty.
- **`gh` rate limits / hammering.** One provider call per (workflow, namespace) per TTL window; narrowing is local;
  in-flight dedupe; stale-if-error keeps the menu useful offline.
- **LSP client filtering quirks with `/` tokens** (word-boundary behavior differs across clients). Mitigated by
  server-provided `textEdit` + `filterText = namespace/name`, and validated by the nvim smoke test before release.
- **Cross-repo version skew.** Phases 4/5 land in `sase-core` before Phase 6 verifies end-to-end; agents follow the
  existing core-ref/CI update policy used by prior sase-core-touching changes.
- **Stale cache showing deleted/renamed repos.** Accepted tradeoff at 10-minute TTL; a wrong acceptance fails downstream
  in `resolve_gh_ref` with today's error behavior, and the next fetch corrects the list.

## Out of Scope / Future Work

- **Owner/namespace completion** (`#gh:` with no `/` yet — e.g. from `github_orgs` config + MRU owners). Natural
  follow-up; the detector/hook design leaves room for it.
- A GitLab/other-VCS plugin itself (this plan only guarantees the seam exists and is documented).
- Unauthenticated REST fallback for public repos (would add an HTTP client + a second auth story to sase-github).
- `completionItem/resolve`-based lazy documentation enrichment (README fetch etc.) — the server already advertises
  resolve support if we ever want it.
- Repo completion inside the `#+` project menu or ChangeSpec refs — unrelated surfaces.
