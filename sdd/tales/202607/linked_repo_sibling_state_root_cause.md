---
create_time: 2026-07-06 18:12:38
status: done
prompt: sdd/prompts/202607/linked_repo_sibling_state_root_cause.md
---
# Root Cause + Fix: Linked-Repo ProjectSpecs Created Without `PROJECT_STATE: sibling`

## Question Being Answered

The `sase-telegram` and `sase-core` ProjectSpecs existed with `WORKSPACE_DIR` but **no** `PROJECT_STATE: sibling`, which
is what broke opened-marker recording and commit finalization (fixed downstream by
`sdd/tales/202607/linked_repo_finalizer_blindness.md`). The user never targeted these repos directly with a VCS xprompt
workflow — agents created them — and agents _should_ have created them as siblings. Why didn't they? This plan pins the
upstream root cause and fixes the creation paths.

## Root Cause (verified)

### 1. Exactly one code path ever stamps `sibling`, and it is double-gated

`PROJECT_STATE: sibling` is written **only** by `_materialize_sibling_project_context()`
(`src/sase/main/workspace_handler_context.py`), reached **only** from `resolve_project_context()` when **both**:

- (a) the requested project's ProjectSpec is missing or has no `WORKSPACE_DIR`, **and**
- (b) the _current_ project can be inferred from cwd (`_current_project_context()` → `infer_project_name_from_cwd()`),
  because the linked-repo config is resolved relative to the current project.

There is no other writer and no reconciliation. Any linked-repo spec that comes into existence with a `WORKSPACE_DIR`
through _any other path_ parses as implicit `active` forever, so `is_sibling` is false for every consumer (opened-marker
recording, finalizer, etc.).

### 2. Gate (b) is broken from every numbered agent workspace (reproduced live)

From a numbered gh workspace, `infer_project_name_from_cwd()` returns `None`:

- The checkout marker (`.sase/checkout.json`) records the **plain repo name** (`project_name='sase'`), not the canonical
  project key (`gh_sase-org__sase`).
- The workspace provider name is likewise the plain `sase`; step 2 of inference requires
  `~/.sase/projects/sase/sase.sase` to exist — it doesn't (and must not).
- `scan_projects_for_cwd()` cannot map registry-based numbered workspaces (`~/.local/state/sase/workspaces/...`) back to
  `gh_sase-org__sase`, whose `WORKSPACE_DIR` is the primary checkout under `~/projects/github/`.
- Nothing consults the `SASE_AGENT_PROJECT_FILE` / `SASE_LINKED_REPOS_JSON` env that the agent runtime already has.

Consequence, reproduced today: `sase workspace open -p sase-github -r "..." <N>` from an agent workspace exits 2 with
`Project 'sase-github' has no WORKSPACE_DIR in ...` — the _same_ failure agent `3.f1` hit at 07:07 (chat
`gh_sase_org__sase-ace_run-260706_070145.md`) and that `sdd/tales/202607/sase_telegram_mit_license.md` documents as a
known "registration gap", telling agents to fall back to `SASE_LINKED_REPO_<NAME>_DIR` env. That workaround bypasses
`workspace open` entirely — so the one path that could have stamped `sibling` (and recorded the opened marker) never ran
for those agents.

### 3. Meanwhile, several flows mint plain-named stateless ProjectSpecs from cwd/repo-name inference

All keyed by the raw provider workspace name (`sase`, `sase-telegram`, `sase-core`, ...), none stamping any lifecycle
state:

- **Commit workflow**: `get_project_from_workspace()` → `compute_suffixed_cl_name()` → `create_project_file()`. Proven
  by the single record in `~/.sase/logs/project_creation.jsonl`: a phantom plain `sase` project minted at 07:22 today by
  a chop agent's `sase commit` running in a numbered sase workspace. It bricked `sase ace` startup; commit `91743c480`
  ("fix: stop phantom projects from crashing ace startup", 07:58 today) canonicalizes the name through the project alias
  map and refuses names claimed as another project's PROJECT_NAME/alias. **Gap that remains**: linked repos like
  `sase-telegram`/`sase-core` are nobody's alias, so commits from linked workspaces still resolve to the plain name and
  mint a stateless spec. Each linked-repo project dir was born at the exact instant an agent's `sase_git_commit` skill
  use ran from a linked workspace (`sase-github` 06:50, `sase-telegram` 07:06, `sase-core` 08:57 — per
  `skill_uses.jsonl` in each project dir).
- **`ensure_project_file_and_get_workspace_num()`** (`src/sase/main/utils.py`): bootstraps a spec for the raw
  `get_workspace_name()` result. Its `_get_project_name()` does **not** canonicalize through the alias map (the 07:58
  fix only patched `get_project_from_workspace()`). Launch-request callers now pass `create_missing=False`, but the
  default is still `True` for other callers.
- **gh plugin `_resolve_repo_path_ref()`** (`sase-github/src/sase_github/workspace_plugin.py`): for `#gh:user/repo` refs
  it creates the spec via `set_workspace_dir()` (+ display-name write) with **no lifecycle state** — this is the only
  writer that produces the exact observed `WORKSPACE_DIR: /home/bryan/projects/github/sase-org/<repo>/` shape. The
  refresh-docs chops are configured with exactly such refs (`gh_ref=sase-org/sase-telegram`, etc.).
- **`xprompts/refresh_docs.yml` marker step**: still does `mkdir` on `~/.sase/projects/{{ project }}/` with the _raw_
  input. The audit chops were fixed in `91743c480` to route through `resolve_project_alias_ref()`; refresh*docs was
  missed — it recreated the phantom `~/.sase/projects/sase/` dir at 10:39 today, _after* the fix landed.

### 4. Net effect

A stateless spec with `WORKSPACE_DIR` appears via class (3) → gate (a) short-circuits `resolve_project_context()` so
materialization never runs again → implicit `active` forever → `is_sibling` false → opened-marker never recorded →
finalizer blindness. The previous fix hardened the downstream (finalizer/env fallback); this plan fixes the upstream so
linked-repo specs are born (or healed to) `sibling`.

Note on certainty: there is no audit journal for ProjectSpec writes and the two specs were rewritten by the data heal,
so the byte-level writer of the two pre-heal files cannot be pinned with 100% certainty. Every candidate writer belongs
to the class above, and all of them produce stateless specs; the fixes below close the class, not just one instance.

## Fix

All Python-side orchestration in the sase repo plus one chop-yml fix; no Rust core API changes (the lifecycle facade
already exposes read/apply).

### Fix 1: `sase workspace open` treats configured linked repos as siblings regardless of spec state

In `resolve_project_context()` (`src/sase/main/workspace_handler_context.py`), when the requested project matches a
configured linked repo — checked first against `linked_repo_metadata_from_env(os.environ)` (has `name`, `primary_dir`,
`workspace_strategy`), falling back to the existing current-project config resolution:

- **Spec missing / no `WORKSPACE_DIR`**: materialize the sibling context directly from the env metadata (`primary_dir`),
  with the same existence/git-repo validation as today, _without_ requiring `_current_project_context()` to succeed.
  Keep the existing config-driven path for non-agent contexts.
- **Spec present with `WORKSPACE_DIR` but implicit lifecycle state**: heal it — stamp `PROJECT_STATE: sibling` through
  the existing `_ensure_sibling_project_spec()` (which already refuses to overwrite an _explicit_ non-sibling state,
  preserving user intent).

Result: `is_sibling` is truthful for every current and future consumer, stateless specs self-heal on next open, and the
documented env-var workaround in plans/tales becomes unnecessary.

### Fix 2: make current-project inference canonicalize plain names

In `infer_project_name_from_cwd()` (`src/sase/bead/project_name.py`), canonicalize the marker/provider-derived name
through `resolve_project_alias_ref()` (best-effort, guarded like the 07:58 commit-path fix) before the spec-existence
check, so `sase` resolves to `gh_sase-org__sase` from numbered workspaces. This unbreaks `_current_project_context()`
(and other cwd-inference consumers) from agent workspaces.

### Fix 3: sibling-aware minting + canonicalized bootstrap names

- `_get_project_name()` in `src/sase/main/utils.py` canonicalizes through the alias map, matching the fixed
  `get_project_from_workspace()`.
- When `create_project_file()` is asked to mint a name that matches a configured linked repo per
  `linked_repo_metadata_from_env()`, create the spec as a **sibling** (`PROJECT_STATE: sibling` +
  `WORKSPACE_DIR: <primary_dir>`) instead of an empty file — directly encoding "agents create linked-repo projects as
  siblings". Non-linked names keep today's behavior (empty spec + creation log + ref-owner refusal).

### Fix 4: refresh_docs chop stops minting phantom project dirs

Mirror the audit-chop fix in `xprompts/refresh_docs.yml`: resolve `{{ project }}` through `resolve_project_alias_ref()`
in both the `count_commits` and `update_marker` steps before building the marker path.

### Data heal (local machine, small)

- `sase-telegram` / `sase-core`: already healed to `sibling` (previous session); `sase-github` was healed today via
  proper sibling materialization during this investigation. `sase-nvim` has no spec and will self-heal via Fix 1 on
  first open.
- Move `~/.sase/projects/sase/refresh_docs_marker` to `~/.sase/projects/gh_sase-org__sase/refresh_docs_marker`
  (preserves refresh cadence under the canonical key after Fix 4), then remove the now-empty phantom
  `~/.sase/projects/sase/` dir.

## Tests

- `tests/main/test_workspace_handler_*`: env-based sibling materialization succeeds when cwd inference fails;
  implicit-state spec with `WORKSPACE_DIR` gets healed to `sibling` on open; explicit non-sibling state still raises;
  non-linked projects unchanged.
- `tests/bead/` (project-name inference): marker/provider plain name that is another project's PROJECT_NAME/alias
  resolves to the canonical key; unresolvable names keep current behavior.
- `tests/workflows/commit/` (or existing project_file_utils coverage): minting a configured linked-repo name produces a
  sibling spec with `WORKSPACE_DIR`; non-linked names still produce today's empty spec; alias-claimed names still
  refused.
- Keep the finalizer/linked-repo suites green (`tests/llm_provider/test_commit_finalizer_siblings.py`,
  `tests/test_linked_repos.py`, `tests/main/test_workspace_handler_list_path.py`).

## Verification

`just install`, targeted pytest for the touched modules, then `just check`. Known environment caveats: the full test
phase can be SIGTERM-killed in the sandbox (exit 144 — not a real failure; fall back to ruff/mypy plus targeted pytest),
and there are 8 pre-existing `llm_provider` `invoke_agent` failures caused by the dev env's `default_effort: xhigh`.

## Out of Scope

- Rust core (`sase-core`) changes.
- Re-keying existing plain-named sibling projects to canonical `gh_*` keys (eradicate-raw-project-keys territory).
- Teaching `scan_projects_for_cwd()` about registry-based numbered workspaces (Fix 2's alias canonicalization covers the
  practical case; a deeper mapping can be a follow-up).
- Healing linked-repo ProjectSpecs on other machines (Fix 1 makes them self-heal on next `workspace open`).
