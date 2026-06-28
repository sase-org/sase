---
create_time: 2026-06-28 08:38:11
status: wip
prompt: sdd/prompts/202606/memory_init_fold_commit.md
---
# Plan: Fold uncommitted `memory/` edits into the `sase memory init` commit

## Problem & product context

When a user manually edits a memory note (e.g. `memory/obsidian.md`, or adds a new short note), those edits are what
make `sase memory init` decide to regenerate the derived instruction files (`AGENTS.md`, the provider shims
`CLAUDE.md`/`GEMINI.md`/ `QWEN.md`/`OPENCODE.md`, `memory/sase.md`, `memory/README.md`). Today this regeneration path
**breaks** when the user's source edits are still uncommitted, and the user experiences it as "`sase memory init` errors
when the working directory has uncommitted changes."

### What actually happens today (grounding the design)

There is **no upfront "dirty working tree" guard**. The real failure is downstream, in `_deploy_to_project_repo`
(`src/sase/main/init_memory_handler.py`):

1. `sase memory init` writes its regenerated files and stages **only** the files it itself wrote/deleted plus
   `memory/sase.md` (`written_paths ∪ deleted_paths ∪ {memory/sase.md}`, lines 151–167). The user's uncommitted
   **source** note (e.g. `memory/obsidian.md`) is _not_ in that set, so it is not staged.
2. It commits those staged files with a fixed message `chore: run sase init memory` + a `SASE_TYPE=memory` footer (lines
   185–200).
3. It then runs `git pull --rebase` (line 206), which **fails on a dirty working tree** ("cannot pull with rebase: You
   have unstaged changes"), returning exit 1.

So today the command makes a _partial_ commit (the regenerated files only) and then dies on pull, leaving the user's
source edit uncommitted and the repo in a half-done state. That is the bug we are fixing.

### Desired behavior

When the **only** uncommitted changes are under `memory/` (the source notes that drove the regeneration),
`sase memory init` should commit those edits **together** with the files it regenerates, in a **single** commit, using a
**user-provided commit message**. The user should not have to think about the conventional-commit tag: we supply a
sensible default `<tag>(<scope>):` prefix (default `docs(memory):`) and let the user override it.

When there are uncommitted changes **outside** `memory/`, we must not silently sweep them in; instead we fail **cleanly
and early** with an actionable message (replacing today's cryptic mid-flight pull failure).

### Design goals (intuitive, reliable, beautiful)

- **Intuitive** — the common case (edit a note, run `sase memory init`) just works: one prompt, one commit, your
  message.
- **Reliable** — never silently absorbs unrelated changes; degrades safely in non-interactive/automation contexts; the
  index is left clean if the user aborts.
- **Beautiful** — a tasteful, framed summary of exactly which memory files are being folded in, a clear prompt that
  pre-states the default tag, and an echo of the final composed commit subject before committing.

## Scope

- **In scope:** the **project repo** path (`_deploy_to_project_repo`) of `sase memory init` (and its `sase init memory`
  alias).
- **Out of scope:** the home/chezmoi deploy path (`_deploy_to_chezmoi` / `defer_chezmoi_paths`). The user's scenario is
  the project repo. Folding home-level memory edits could be a follow-up; this plan explicitly does not change that
  path.

## Behavior specification

Let the **pre-init dirty set** be the repo's uncommitted paths (staged + unstaged + untracked) captured **before**
`sase memory init` writes any of its own files. This is the key to correctly distinguishing _user_ changes from _init's
own_ regeneration: note that `AGENTS.md` and the provider shims live at the **repo root** (not under `memory/`), so
classifying _after_ init writes would wrongly bucket init's own output as "non-memory."

Partition the pre-init dirty set into:

- `memory_dirty` — paths under `<project_root>/memory/`.
- `other_dirty` — everything else.

Decision table (only relevant when committing, i.e. not `--no-commit` and not `--check`):

| Pre-init state                                      | init has changes to commit?               | Behavior                                                                                                                                                                           |
| --------------------------------------------------- | ----------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| clean (`memory_dirty` and `other_dirty` both empty) | yes                                       | **Unchanged from today**: commit regenerated files with the default `chore: run sase init memory` message.                                                                         |
| clean                                               | no                                        | "nothing to commit" no-op (unchanged).                                                                                                                                             |
| `other_dirty` non-empty                             | yes, or `memory_dirty` non-empty          | **Refuse early** (exit 1) with a clear message listing the offending non-`memory/` paths; do not commit. Regenerated files remain written-but-uncommitted (same as `--no-commit`). |
| `other_dirty` non-empty                             | no init changes **and** no `memory_dirty` | Fall through to the existing "nothing to commit" no-op (no new error on a previously-clean exit).                                                                                  |
| `memory_dirty` non-empty, `other_dirty` empty       | (any)                                     | **Fold**: stage the `memory_dirty` paths alongside init's regenerated files and make a **single** commit using the user's message (see below).                                     |

### Commit message resolution (the "fold" case)

The commit subject is resolved in this priority order:

1. **`--message/-m <subject>` flag** — use it (no prompt). This is the non-interactive / automation path.
2. **Interactive (stdin is a TTY)** — show the framed summary of `memory_dirty` files, then prompt for a one-line
   subject.
3. **Non-interactive, no `-m`** — **refuse** (exit 1) with:
   `init memory: memory/ has uncommitted changes to fold into the commit, but no commit message was provided and stdin is not a TTY. Re-run with --message "<subject>", or --no-commit to skip committing.`

Tag handling (so the user "doesn't need to worry about the tag"):

- If the provided/typed subject already begins with a conventional header (`^<tag>(\(scope\))?!?: `, where `<tag>` is
  one of the project's allowed tags `feat|fix|perf|refactor|docs|test|build|ci|style|revert|chore`), use it
  **verbatim**.
- Otherwise **prepend** the default prefix `docs(memory): ` — so a casual `document obsidian vault workflow` becomes
  `docs(memory): document obsidian vault workflow`, while a power user can type `feat(memory): add obsidian note` and
  keep their tag.
- `docs` is the idiomatic default: memory notes + `AGENTS.md` are documentation/instruction content, and the project's
  `sase_git_commit` skill defines `docs` as "documentation-only changes, including README files, docstrings, comments,
  or docs sites." `(memory)` is the scope already used in repo history (`feat(memory): …`).

Then run the final subject through the existing `apply_auto_commit_type_tag(subject, "memory")` so the
`SASE_TYPE=memory` footer is preserved exactly as today (keeps machine-readable provenance consistent).

Abort semantics: an empty typed subject, EOF, or Ctrl-C cancels the commit (exit 1) with a clear note; **nothing is
staged or committed** in that case (message is resolved _before_ any extra staging, so the index is left exactly as init
found it).

### Ordering guarantee (clean index on abort)

Resolve the commit message (prompt/flag/refuse) **before** staging anything. Only once a message is in hand do we stage
init's files + the `memory_dirty` paths and commit. This guarantees the working tree/index is untouched if the user
backs out.

## UX / copy (the "beautiful" part)

Use the house Rich style already used elsewhere for human-facing prompts (`border_style="cyan"`, escaped content), while
keeping plain `print(..., file=sys.stderr)` for status/refusal lines to stay consistent with the surrounding deploy
output.

Fold prompt (TTY):

```
╭─ Uncommitted memory changes ──────────────────────────────╮
│ These memory/ edits will be committed together with the   │
│ regenerated AGENTS.md and provider shims:                 │
│                                                           │
│   • memory/obsidian.md   (modified)                       │
│   • memory/new_note.md   (new)                            │
╰───────────────────────────────────────────────────────────╯
A `docs(memory):` tag is added automatically if you omit one.

Commit message ›
```

After input, echo the composed subject before committing:

```
init memory: committing as: docs(memory): document obsidian vault workflow
```

Foreign-changes refusal (stderr, exit 1):

```
init memory: refusing to commit — uncommitted changes outside memory/ would be left behind:
  • src/sase/foo.py   (modified)
Commit or stash these changes and re-run `sase memory init`, or pass --no-commit to skip
the git commit/push step. The regenerated memory files have been written but not committed.
```

## Technical design

### New/changed modules

1. **`src/sase/main/init_memory/git_state.py`** (new) — _pure_ helpers, no subprocess, so they are trivially
   unit-testable:
   - Parse `git status --porcelain=v1 --untracked-files=all -z` output into structured entries (status code + path). The
     NUL-delimited (`-z`) format is chosen specifically so renames and unusual filenames are handled correctly (the
     existing `git_changed_files` helper in `llm_provider/commit_finalizer_git.py` naively does `line[3:]` and
     mis-parses renames — not safe for our classification, so we use a dedicated `-z` parser here).
   - `classify(entries, memory_rel) -> (memory_dirty, other_dirty)` partitioning by whether the repo-relative path is
     under the `memory/` dir.
   - A small frozen dataclass `PreInitGitState(git_root, memory_dirty, other_dirty)`.

2. **`src/sase/main/init_memory/commit_message.py`** (new) — _pure_ commit-message composition:
   - `is_conventional_header(subject) -> bool` (regex over the allowed tag set).
   - `compose_fold_subject(subject, default_prefix) -> str` (verbatim vs prepend).
   - `build_fold_commit_message(subject) -> str` = `compose_fold_subject(...)` then
     `apply_auto_commit_type_tag(..., "memory")`.
   - Reuses `apply_auto_commit_type_tag` from `sase.workflows.commit.runtime_tags`.

3. **`src/sase/main/init_memory/constants.py`** — add `MEMORY_FOLD_DEFAULT_PREFIX = "docs(memory): "` (keep
   `PROJECT_COMMIT_MESSAGE` for the clean-tree default).

4. **`src/sase/main/init_memory_handler.py`** — orchestration (subprocess + I/O lives here, matching the existing
   all-Python git deploy, and so the existing tests' `init_memory_handler.subprocess.run` monkeypatch continues to cover
   it):
   - New `_capture_pre_init_git_state(project_root) -> PreInitGitState | None`: `git rev-parse --show-toplevel` then
     `git status --porcelain=v1 --untracked-files=all -z`, classify via `git_state.py`. Returns `None` if not a git repo
     / git missing.
   - `run_init_memory`: capture the state **before** `_initialize_memory_root` writes (guarded by
     `not no_commit and not check`); pass it + the `--message` value into `_deploy_to_project_repo`.
   - `_deploy_to_project_repo(project_result, *, no_commit, git_state, message)`:
     - When `git_state` is present, reuse `git_state.git_root` (avoid a second `rev-parse`); when it's `None`, keep
       today's own `rev-parse` so the existing "not a git repo" / "git not found" error messages and exit codes are
       preserved.
     - Implement the decision table above: foreign-changes refusal, message resolution (`_resolve_fold_commit_message`,
       which owns the TTY check + prompt + abort), extra staging of `memory_dirty`, then the existing commit/pull/push.
     - Reuse the existing `_stdin_is_tty` pattern from `src/sase/prompt/cli_maintenance.py` (or a tiny local equivalent)
       for the TTY gate; wrap `input()` in `try/except (EOFError, KeyboardInterrupt)` → abort.

### Parser changes

- **`src/sase/main/parser_memory.py`** — add `-m/--message MESSAGE` to the `init` subparser (help: "Commit subject for
  folding uncommitted memory/ changes; a `docs(memory):` tag is added if omitted").
- **`src/sase/main/parser_init.py`** — add the same `-m/--message` to the `sase init memory` **alias** subparser (it
  defines its own flags today), for parity. Confirm `run_init_memory` reads `getattr(args, "message", None)` so both
  entry points work.

No keymap/`default_config.yml` changes (no keymaps involved).

### Rust core boundary (explicit call)

This stays in **Python**, consistent with the existing implementation and the boundary litmus test:

- The entire `sase memory init` deploy already runs git via raw Python `subprocess` and is **not** routed through
  `sase_core`. This change is a CLI maintenance workflow (prompting, message composition, commit orchestration) —
  presentation/glue, not shared cross-frontend domain behavior. A web/editor frontend would not re-run
  `sase memory init` interactively.
- The one arguably-core primitive is "parse porcelain output into paths." The Rust `git_query` module already owns
  sibling parsers (`parse_git_local_changes`, `parse_git_name_status_z`, `parse_git_conflicted_files`) but **none**
  returns a working- tree path list, and `parse_git_local_changes` returns only a raw blob. Adding a porcelain-paths
  parser to `sase-core` + bindings + cross-repo tests would be disproportionate to this change and would still leave the
  orchestration in Python.
- **Decision:** implement the porcelain parser locally in Python now; note as a possible future follow-up that, if
  another frontend needs the same classification, the pure `git_state.py` parser can be promoted into `sase-core`'s
  `git_query` module and exposed via `sase_core_rs`. This is flagged for the reviewer rather than silently chosen.

## Testing strategy

The full suite is SIGTERM-killed in this sandbox, so rely on **targeted** pytest modules + static gates (`just lint` =
ruff + mypy). New/updated tests:

1. **`tests/main/test_init_memory_git_state.py`** (new) — unit-test the pure parser + classifier:
   modified/added/deleted/untracked entries, a rename moving a file into/out of `memory/`, and the memory-vs-other
   partition. No subprocess.

2. **`tests/main/test_init_memory_commit_message.py`** (new) — unit-test tag detection, prepend-vs-verbatim, and that
   `SASE_TYPE=memory` footer is preserved (`build_fold_commit_message`).

3. **`tests/main/test_init_memory_commit.py`** (extend, following its existing `fake_run`/`run_precommit` monkeypatch
   style; extend `fake_run` to answer `status`):
   - **Regression**: clean tree → still commits with `chore: run sase init memory\n\nSASE_TYPE=memory`. Update the
     existing verb-sequence assertion to account for the new capture-step `status` call (and the moved `rev-parse`).
   - Memory-only dirty + `--message "document obsidian vault workflow"` → single commit with subject
     `docs(memory): document obsidian vault workflow`, the memory path is staged (`git add -- memory/…` present),
     pull+push run, exit 0.
   - Memory-only dirty + `-m "feat(memory): add note"` → tag preserved verbatim.
   - Memory-only dirty + TTY prompt (`patch("builtins.input", return_value=...)` + force `_stdin_is_tty` True) → same as
     the `-m` case.
   - Memory-only dirty + non-TTY + no `-m` → refuse, exit 1, no commit.
   - Empty input / EOF at prompt → abort, exit 1, no commit, index untouched.
   - Foreign (non-`memory/`) dirty → refuse early, exit 1, no `commit` call, regenerated files written.
   - `--no-commit` path unchanged (existing test stays green; capture is skipped).
   - `sase init memory --message …` alias path resolves identically.

## Docs

- **`docs/init.md`** — extend the memory-init flag table (currently documents `--check`, `-C`) with the new
  `-m/--message`, and add a short subsection describing the fold-on-commit behavior and the foreign-changes refusal.
  (`docs/cli.md` is a hand- maintained index and needs no change; `sase validate` runs only `init --check` /
  `sdd validate` and does not gate docs.)
- Glance at `docs/memory.md` for a one-line cross-reference if natural.

## Verification checklist

1. `just install` (ephemeral workspace may have stale deps).
2. `just lint` (ruff + mypy) — must pass.
3. Targeted tests:
   `pytest tests/main/test_init_memory_git_state.py tests/main/test_init_memory_commit_message.py tests/main/test_init_memory_commit.py`.
4. `sase validate` — confirm `init --check` still passes (the freshness gate). The fold logic never runs under `--check`
   (it returns before the deploy step), so the gate is unaffected.
5. Manual smoke (interactive): in a scratch git repo with a managed memory setup, edit a note, run `sase memory init`,
   confirm the prompt, the single combined commit, and the composed subject; then repeat with an unrelated dirty file to
   confirm the clean refusal.

## Risks & mitigations

- **Misclassifying init's own output as "foreign."** Mitigated by capturing the dirty set **before** init writes
  (root-level `AGENTS.md`/shims are otherwise non-`memory/`).
- **Hanging in automation.** Mitigated by the `--message` flag + non-TTY refusal; the `sase validate` gate uses
  `--check`, which never reaches this path.
- **Partial/dirty index on abort.** Mitigated by resolving the message before any extra staging.
- **Edge git states** (untracked new note, deleted note, rename in/out of `memory/`). Handled by the `-z` porcelain
  parser and `git add -- <path>` (which stages deletions for tracked files); covered by `git_state` unit tests.
