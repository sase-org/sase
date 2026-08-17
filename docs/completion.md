# Shell Completion

`sase completion` generates native shell-completion scripts for `zsh`, `bash`, and
`fish` from the live `sase` argparse tree, so pressing `<TAB>` anywhere in the command
line offers the right commands, options, static choices, and live values — bead ids with
titles, project display names, xprompt names, and more — with no perceptible latency.

The grammar (commands, options, choices, mutex groups) is generated fresh every time
from the same tree `--help` reads, so it cannot drift out of sync with the CLI. Only
_values_ — beads, projects, repos, and the like — are fetched live, through a narrow,
cached fast path.

## Quick Start

Pick your shell and write the script somewhere your shell already scans, or let
`sase completion install` find that place for you:

```bash
sase completion install          # detect the shell, write, zcompile (zsh), verify, stamp
sase completion install zsh      # or name one explicitly
sase completion install -d       # dry run: print the plan, touch nothing
```

Open a new shell afterward — completion scripts are read once, at shell startup.

Manual install, if you'd rather manage the file yourself:

```bash
sase completion zsh   -o ~/.zfunc/_sase
sase completion bash  -o ~/.local/share/bash-completion/completions/sase
sase completion fish  -o ~/.config/fish/completions/sase.fish
```

**Never** `eval "$(sase completion zsh)"` in an rc file. That pays a full `sase` startup
(300–640 ms) on every new shell; write the script to a file instead.

For zsh, the directory must be on `fpath` **before** `compinit` runs, or the completion
silently never loads even though the file is sitting right there.
`sase completion install` prefers a directory your shell already scans — and, when you
run a framework like oh-my-zsh, its `completions` drop-in directory, which the framework
guarantees is on `fpath` before `compinit`. If it has to fall back to a conventional
directory (`~/.zfunc`), it prints the exact line to add:

```zsh
fpath=(~/.zfunc $fpath)   # must appear BEFORE compinit
```

`sase completion install` never edits `~/.zshrc`, `~/.bashrc`, or any other rc file —
only the completion script itself.

## What `install` Does

1. **Detects the shell** from `$SHELL` and the parent process, unless one is given
   explicitly.
2. **Chooses a target directory**, in order: `-t/--target`, then `SASE_COMPLETION_DIR`,
   then a shell framework's `completions` drop-in directory, then the first writable
   directory the shell actually scans, then a conventional fallback (`~/.zfunc` for zsh,
   `~/.local/share/bash-completion/completions` for bash, `~/.config/fish/completions`
   for fish). Two rules shape that middle ground:
   - **A framework's drop-in directory wins, and is created if the framework ships the
     `fpath` entry without the directory** — on oh-my-zsh that is
     `~/.oh-my-zsh/custom/completions`. It is the only scanned entry whose ordering is
     guaranteed, because the framework puts it on `fpath` itself, before it runs
     `compinit`. A plain user directory like `~/.zfunc` is frequently appended _after_
     `compinit`, where a script in it never loads — and the `fpath` probe cannot tell
     the two apart, since it reads `fpath` once rc processing has already finished.
   - **Framework plugin directories and caches are never used**, even though they are
     scanned and writable. An enabled plugin's own directory is on `fpath` only while
     that plugin is enabled, so a script dropped there hijacks an unrelated project's
     tree and disappears the day the plugin is turned off.

   Among the remaining candidates, home directories win over system-wide ones.

3. **Writes** the script atomically, and removes the script a previous install stamped
   somewhere else, so changing targets never leaves a second copy behind.
4. **`zcompile`s** the zsh script. This is not an optimization — an uncompiled ~300 KB
   script costs 79–84 ms to parse on the first `<TAB>` of every new shell; the compiled
   `.zwc` answers in well under a millisecond.
5. **Verifies registration** for zsh by probing `${_comps[sase]}` in a real,
   non-interactive shell. A file that exists but was written to a directory `compinit`
   never scanned is a silent no-op — `install` catches that and tells you exactly what
   to fix.
6. **Stamps** `~/.sase/completion/stamp/<shell>.json` with the sase version, the spec's
   structural digest, and the target path, so `sase completion list` and `sase doctor`
   can tell a real install from a stray file.
7. **Reports** every step's outcome and prints the recommended `zstyle` snippet below.

`sase completion list` shows every shell's generator availability, install status,
target path, `.zwc` freshness, and stamp version in one table. `sase doctor` includes
the same checks as a non-blocking advisory group (`completion.install`,
`completion.registration`); file presence alone is never treated as evidence of a
working install.

## The Recommended `zstyle` Snippet

zsh's compsys is opt-in for grouping, descriptions, and menu selection.
`sase completion install` prints this snippet at the end of a successful install; add it
to your `.zshrc` **after** `compinit`:

```zsh
# Recommended compsys styles for sase (grouped, described, menu-selected):
zstyle ':completion:*' menu select
zstyle ':completion:*' group-name ''
zstyle ':completion:*:descriptions' format '%F{yellow}-- %d --%f'
zstyle ':completion:*' verbose yes
zstyle ':completion:*' list-grouped true
zstyle ':completion:*' use-cache on
```

`use-cache on` matters beyond cosmetics: it is what lets the dynamic-value layer below
actually cache results in-shell instead of re-forking `sase` on every keystroke.

## Value Kinds And Caching

Options and positionals whose value can't be enumerated statically (bead ids, project
names, repo names, plan references, and more) complete through
`sase completion candidates <KIND> [PREFIX]` — a pre-argparse fast path in `entry.py`
that never imports the full CLI, ACE, or Rust extension surface it doesn't need, and
answers in well under its latency budget for a warm process. `KIND` completes to the
kinds this build can actually answer, so `sase completion candidates <TAB>` is the
authoritative list.

Glossary terms are a worked example of how a kind is shaped for a shell rather than for
a report: `sase glossary show <TAB>` offers slug-form references (`agent-hood`), because
`sase glossary` resolves references case- and separator-insensitively and a slug is the
one form that never needs quoting on a command line.

That fast path is still a subprocess, so every generated script caches its output rather
than calling it on every keystroke — necessary once something like
`zsh-autosuggestions`' `completion` strategy is in the mix, which re-triggers completion
on every character typed:

- **zsh** caches through compsys's own `_retrieve_cache`/`_store_cache` machinery
  (subject to your `use-cache on` setting above), keyed per value kind.
- **bash** caches into a `declare -gA` associative array scoped to the shell session.
- **fish** forks a subshell for every `(...)` command substitution, so shell-side
  caching doesn't carry between keystrokes; it relies on the fast path's own on-disk
  cache instead (see `SASE_COMPLETION_NO_CACHE` below).

All three pass the **full** candidate set to the shell's own filtering rather than the
typed prefix, so one cached fetch serves the whole word, not just one keystroke.

`sase run`'s `PROMPT` argument is a special case: rather than a single value kind, it
completes native file paths (for editor-drafted prompt files) _and_ stored xprompt names
together. `#`, `%`, and `@` reference completion inside the prompt text itself is
deferred — see [Deferred](#deferred) below.

### Environment Variables

| Variable                    | Effect                                                                                     |
| --------------------------- | ------------------------------------------------------------------------------------------ |
| `SASE_COMPLETION_CACHE_TTL` | Seconds an in-shell (zsh/bash) cached kind stays fresh. Default: `60`.                     |
| `SASE_COMPLETION_NO_CACHE`  | Set to `1` to bypass the on-disk candidates cache entirely (fish, or debugging any shell). |
| `SASE_COMPLETION_DIR`       | Force `sase completion install`'s target directory, overriding auto-detection.             |

## Refresh On Update

`sase update` can regenerate, `zcompile`, and re-stamp every previously installed
completion script after a successful upgrade, so an installed script never drifts stale
behind the CLI it completes. This is gated behind the `completion_refresh_on_update`
beta feature flag (default off) — rewriting files on every machine during an unrelated
command is exactly the kind of early-landed path that flag exists for. Enable it once
you trust the generator:

```bash
sase flag list completion_refresh_on_update   # inspect
sase -f completion_refresh_on_update update   # try once, without changing the default
```

Refresh failures are reported but never fail `sase update` itself.

## Troubleshooting

Start with `sase doctor` — it runs the same install and registration checks described
above:

```bash
sase doctor -v                    # human report, including completion checks
sase doctor -C completion.install
sase doctor -C completion.registration   # deep check: probes ${_comps[sase]} for real
```

Common issues:

- **Nothing completes in a new shell.** Check `sase completion list` for the install
  status and target path. For zsh specifically, confirm the target directory appears in
  `fpath` _before_ `compinit` — `sase doctor -C completion.registration` catches this
  even when the script file is present.
- **Completion is slow.** A cold first `<TAB>` for a zsh script that was written but
  never `zcompile`d costs 79–84 ms; re-run `sase completion install` to compile it. A
  slow _dynamic_ value (a kinded slot) points at the candidates fast path itself —
  `sase completion candidates <kind>` directly to isolate it from shell overhead.
- **A completion looks stale.** In-shell caches (zsh, bash) expire after
  `SASE_COMPLETION_CACHE_TTL` seconds (default 60); a new shell always starts cold.

### Measured Latency

Approximate, measured on this repo's live command tree (331 parsers / 809 options / 140
positionals):

| Stage                                           | zsh                                                    | bash                                         | fish                       |
| ----------------------------------------------- | ------------------------------------------------------ | -------------------------------------------- | -------------------------- |
| Parse/load the generated script (per new shell) | 0.4–12 ms (`.zwc`) / 79–84 ms (uncompiled)             | ~4–5 ms (uncompiled; no zcompile equivalent) | not independently measured |
| Warm `<TAB>` (cached value kind)                | 0.4–12 ms                                              | ~9–10 ms                                     | not independently measured |
| Cold `<TAB>` (first fetch of a value kind)      | one `sase completion candidates` subprocess, ~65–90 ms | ~65–90 ms                                    | not independently measured |

zsh and bash numbers above are directly measured (zsh via the real-shell smoke tests
under `tests/completion/`; bash via sourcing the generated script and timing `_sase`
before and after its in-shell cache is populated). Fish was not available in the
environment this phase was implemented in, so its numbers are not independently
confirmed; expect figures close to bash's, since fish's `__sase_candidates` helper calls
the same fast path and fish has no script-compilation step either.

## Deferred

Recorded here rather than shipped in this epic — each is cheap to add later once the
spec model exists, and none blocks the core experience:

- **`#`/`%`/`@` reference completion inside `sase run`'s prompt text.** Today the
  `PROMPT` argument completes as a whole word (files or an xprompt name); completing an
  xprompt reference, directive, or artifact reference _embedded inside_ a longer prompt
  string is future work.
- **A `carapace-spec` emitter** from the same `CompletionSpec` model, for nushell,
  elvish, and PowerShell. SASE targets POSIX hosts today.
- **Chezmoi deployment** of the generated scripts on SASE-managed machines, through
  `src/sase/main/_init_chezmoi_deploy.py`.
