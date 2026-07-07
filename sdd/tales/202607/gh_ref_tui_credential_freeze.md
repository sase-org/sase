---
create_time: 2026-07-07 16:04:12
status: done
prompt: sdd/prompts/202607/gh_ref_tui_credential_freeze.md
---
# Fix ace TUI freeze from interactive git credential prompts (`Username for 'https://github.com':`)

## Symptom

While typing in the `sase ace` prompt input, the text `Username for 'https://github.com':` sometimes appears inline in
the prompt widget and the entire TUI becomes unresponsive until the user kills and restarts it. Screenshot evidence
(`20260707_155324.png`) shows the prompt containing `#gh:steveyegge/be` with the git credential prompt appended at the
cursor position.

## Root cause

The freeze is a chain of three defects; the screenshot captures all of them firing together:

1. **Prompt completion triggers a side-effectful ref resolution.** `resolve_prompt_completion_base_dir()` in
   `src/sase/ace/tui/widgets/prompt_completion_root.py` claims in its docstring to be "intentionally read-only", but
   `_resolve_registered_base_dir()` calls `workspace_provider.resolve_ref(ref, workflow_type)` for every registered
   workflow ref found in the prompt (only the bare-git `"git"` type is special-cased via
   `_KNOWN_PROJECT_ONLY_WORKFLOW_TYPES`). For a `#gh:owner/repo` ref, the GitHub plugin's `ws_resolve_ref` →
   `resolve_gh_ref()` → `_resolve_repo_path_ref()` **clones the repository and allocates a project record if the
   workspace dir does not exist** (`src/sase_github/workspace_plugin.py` in the `sase-github` linked repo).

   This resolution runs on the Textual UI thread on the keystroke path:
   - `_prompt_soft_completion.py` → `_fire_prompt_completion_timer()` (debounced per keystroke) calls
     `resolve_prompt_completion_base_dir(text)` synchronously.
   - `_file_completion_refresh.py` / `_file_completion_open.py` / `_file_completion_context.py` call
     `self._prompt_completion_base_dir()` during completion refresh and Ctrl+T handling.

   So while the user is still typing `#gh:steveyegge/be…`, the TUI literally attempts
   `git clone https://github.com/steveyegge/be.git` for the **partial** repo name. This violates the codebase's own
   documented invariants twice over: `memory/tui_perf.md` rule 1 (no synchronous subprocess calls on the event loop),
   and the hazard already documented in `src/sase/history/vcs_xprompt_mru.py` (`_vcs_prefix_ref_is_gone` deliberately
   avoids `resolve_ref` because provider resolve paths _create_ state).

2. **git is allowed to prompt interactively.** `_clone_gh_repo()` runs `git clone` with `capture_output=True` but does
   not disable interactive credential prompting. git's credential prompt opens `/dev/tty` directly, bypassing the
   captured stdout/stderr: it writes `Username for 'https://github.com':` into the raw terminal (corrupting the Textual
   screen at the cursor position) and switches the terminal out of raw mode while it blocks reading keystrokes — which
   is exactly the observed "frozen TUI that eats input". GitHub answers HTTP 401 for unauthenticated requests to
   nonexistent/private repos, so a clone of a partially-typed repo name reliably triggers the prompt. No code in either
   repo sets `GIT_TERMINAL_PROMPT=0` or any equivalent guard today.

3. **HTTPS is used for owners outside `github_orgs`.** `_clone_gh_repo()` picks `git@<host>:owner/repo.git` only when
   the owner is listed in the `github_orgs` config; every other owner gets `https://<host>/owner/repo.git`. The user's
   preference is SSH-first for all GitHub git traffic whenever possible.

Verified not in scope: `sase-core` (Rust) spawns no network git commands (only local bead mutations), so no Rust-side
change is needed. The `gh repo list` call behind the new repo completion menu runs in a thread worker with captured
output and does not prompt; it is not the culprit.

## Fix design (three layers, defense in depth)

### Layer 1 — make prompt-completion base-dir resolution truly read-only (sase repo)

Add a read-only resolution hook so presentation code can ask "where would this ref live?" without mutating anything:

- **`src/sase/workspace_provider/_hookspec.py`**: add an optional first-result hook
  `ws_peek_ref(ref: str, workflow_type: str) -> ResolvedRef | None`, documented as strictly read-only: no cloning, no
  project/workspace creation, no network, no writes. Returns `None` when the ref cannot be resolved from existing local
  state.
- **`_plugin_manager.py` / `_registry.py` / `__init__.py`**: plumb and export a `peek_ref()` function mirroring
  `resolve_ref()`.
- **`prompt_completion_root.py`**: in `_iter_registered_refs` handling, replace the `resolve_ref` call with `peek_ref`.
  When a provider returns `None` (or implements no peek hook), fall back to the existing known-projects lookup
  (`_known_project_base_dir_for_ref`). This makes the current `_KNOWN_PROJECT_ONLY_WORKFLOW_TYPES = {"git"}` special
  case redundant — remove it, since the known-projects fallback now applies uniformly to any provider without a peek
  implementation. Keep the `#cd` flow unchanged (`_resolve_cd_base_dir` still uses `resolve_ref`; the cd resolver is
  verified read-only), or optionally route it through `ws_peek_ref` implemented by the cd plugin for uniformity —
  implementer's choice, with the minimal-diff option preferred.
- **`sase-github` linked repo, `src/sase_github/workspace_plugin.py`**: implement `ws_peek_ref`:
  - `owner/repo` refs: compute `_github_workspace_dir(owner, repo)`; return a `ResolvedRef` only if that directory
    already exists on disk; otherwise return `None`. Never clone, never allocate project names, never write
    `WORKSPACE_DIR`.
  - shorthand / alias / ChangeSpec-name refs: reuse the existing lookups from `resolve_gh_ref` modes 2/3 and the
    alias-record path (these are already read-only); factor the shared lookup out so `resolve` and `peek` cannot drift.

Launch-time resolution (`src/sase/ace/tui/actions/agent_workflow/_ref_resolution.py`) must keep using `resolve_ref` —
cloning on an actual agent launch is intended behavior. Layer 2 makes that path fail fast instead of freezing when
credentials are unavailable.

### Layer 2 — never let sase-spawned git prompt interactively (sase + sase-github repos)

Add one shared helper in the sase repo (suggested home: `src/sase/workspace_provider/utils.py`, which sase-github
already imports from), e.g. `non_interactive_git_env(base: Mapping[str, str] | None = None) -> dict[str, str]`,
returning a copy of the environment with:

- `GIT_TERMINAL_PROMPT=0` — blocks git's HTTPS username/password `/dev/tty` prompt (the exact failure observed); git
  then fails fast with "terminal prompts disabled".
- `GCM_INTERACTIVE=never` — belt-and-braces for git-credential-manager setups.
- `SSH_ASKPASS=/bin/false` + `SSH_ASKPASS_REQUIRE=force` — forces OpenSSH (≥8.4) to fail fast instead of prompting for
  key passphrases on `/dev/tty`. This is preferred over forcing `GIT_SSH_COMMAND="ssh -oBatchMode=yes"` because
  `GIT_SSH_COMMAND` would silently override a user-configured `core.sshCommand`. (Configured non-interactive credential
  helpers and ssh-agent keys keep working — these vars only suppress _prompts_.)

Apply the helper (plus `stdin=subprocess.DEVNULL`) to every sase-spawned git subprocess that can touch a remote:

- `sase-github` `workspace_plugin.py`: `_clone_gh_repo` (the direct culprit); audit the module's other `subprocess.run`
  calls (`gh pr merge` etc. — for `gh` calls additionally set `GH_PROMPT_DISABLED=1` as cheap hardening).
- sase repo network-capable git call sites:
  - `src/sase/vcs_provider/plugins/_git_query_ops.py` (`git ls-remote`, `git fetch origin`)
  - `src/sase/vcs_provider/plugins/_git_commit_dispatch.py` (`git ls-remote --heads origin`)
  - `src/sase/dev_update/detect.py`, `plan.py`, `execute.py` (update-check `git fetch`)
  - `src/sase/workspace_provider/utils.py` `_ensure_git_clone_at` (`git clone` / `git fetch` — origin is a local path
    today, but guard it anyway)

This layer alone fixes the freeze even if some future code path resolves a ref eagerly again: the clone fails
immediately with a captured error instead of hanging on `/dev/tty`.

### Layer 3 — prefer SSH over HTTPS for GitHub clones (sase-github repo)

Change `_clone_gh_repo()` URL selection from "SSH only for `github_orgs` members" to SSH-first for **all** owners:

1. Build the SSH URL (`git@<host>:owner/repo.git`, or `ssh://git@<host>/owner/repo.git` when the configured host embeds
   a port) and attempt the clone non-interactively.
2. On failure, fall back to the HTTPS URL, still non-interactive (this keeps anonymous clones of public repos working on
   machines without GitHub SSH keys).
3. If both fail, raise a `RuntimeError` that includes both attempts' stderr so the launch-failure notification is
   actionable.

No new config keys are introduced (so no `src/sase/default_config.yml` changes); `github_orgs` keeps its other uses but
no longer influences clone protocol.

## Testing

sase repo:

- `prompt_completion_root` unit tests: register a spy workspace provider whose `ws_resolve_ref` raises `AssertionError`
  and whose `ws_peek_ref` records calls/returns a dir — assert that
  `resolve_prompt_completion_base_dir("... #gh:owner/repo ...")`-style prompts (using the spy's workflow type) never
  invoke `ws_resolve_ref`, use the peek result when available, and fall back to known-projects lookup when peek returns
  `None` or is unimplemented.
- `non_interactive_git_env` unit tests: expected vars set, base env preserved, no mutation of `os.environ`.
- Regression tests asserting the guarded call sites pass the env + `stdin=DEVNULL` (monkeypatch `subprocess.run` and
  inspect kwargs) where practical.

sase-github repo:

- `ws_peek_ref`: existing workspace dir → resolved; missing dir → `None`; assert no subprocess is spawned (monkeypatch
  `subprocess.run` to raise).
- `_clone_gh_repo`: SSH URL attempted first for a non-`github_orgs` owner; HTTPS fallback on SSH failure; both-fail
  error message contains both stderrs; env contains `GIT_TERMINAL_PROMPT=0`.

Both repos: run `just check`. Manual verification: in `sase ace`, type `#gh:someowner/doesnotexist` into the prompt —
the completion menu may show an error row, but no clone directory appears under `~/projects/github/`, no credential text
bleeds into the widget, and the TUI stays responsive; launching an agent with a private-repo `#gh` ref fails fast with a
visible error instead of freezing.

## Risks / notes

- The peek hook changes completion base-dir behavior for `#gh:owner/repo` refs pointing at repos that are _not yet
  cloned_: path completion simply stays on the CWD base instead of cloning mid-keystroke. That is the intended behavior
  change.
- Partial-name clones from past freezes may have left empty parent dirs under `~/projects/github/` (e.g. `steveyegge/`);
  cleanup is out of scope.
- `SSH_ASKPASS_REQUIRE` needs OpenSSH ≥ 8.4 (present on this host); on older ssh the var is ignored and behavior
  degrades to today's (git HTTPS prompts are still blocked by `GIT_TERMINAL_PROMPT=0`, which is the observed failure
  mode).
- Linked-repo work must go through `sase workspace open -p sase-github …` (and only there); `sase-core` requires no
  changes for this fix.
