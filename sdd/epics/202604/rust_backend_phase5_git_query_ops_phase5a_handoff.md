---
create_time: 2026-04-29
status: done
bead_id: sase-1a.1
---

# Rust Backend Phase 5A — Audit, Profiling, and Scope Lock

Closes Phase 5A of `plans/202604/rust_backend_phase5_git_query_ops.md`.
Inventories `GitQueryOpsMixin`, lands a focused Git query-op
benchmark, records timings against the Python implementation and the
real `git diff` subprocess, and locks the parser set Phase 5B–5F should
work against.

## Decision: PROCEED with Phase 5 at the narrow shared-core scope. `gix` stays out of scope.

The deterministic parsers in `_git_query_ops.py` cost **single-digit
to low-triple-digit microseconds**. The dominant cost on every realistic
Git query operation is the `git` subprocess fork+exec (~3 ms on a
50-file diff, ~11 ms on a 500-file diff). Parsing is **~150–55× cheaper
than the subprocess**, so a Rust parser cannot move user-perceived
latency on the Git provider hot path.

The motivation for proceeding is therefore the same as Phase 4: lock
down a stable cross-language wire contract for Git query parsing,
collapse a small drift surface between Python and Rust callers, and
keep the migration on the shared-core pattern. Performance is a
**parity, not speedup** target.

The numbers also rule out a `gix` rewrite for Phase 5. If the team ever
wants to attack the subprocess cost itself, that is a much larger
project (process-side linkage to a libgit2/gix runtime, async
orchestration of fetch/rebase, error-mapping for libgit2 codes, and
cross-platform pre-built binaries) and should land as a separate plan.
For now, **keep shelling out to `git` and only port the deterministic
parsers**. This is the recommendation already encoded in the Phase 5
plan's option A; the bench numbers below confirm it.

## Workstation and environment

- Host: `athena` (Linux 6.12, x86_64)
- CPU: AMD Ryzen Threadripper 3970X 32-Core
- Python: 3.14.3 (default `.venv`)
- Rust extension: `sase_core_rs` built via `just rust-install`
  (PyO3 0.22, release profile). The Phase 5A bench does not exercise
  Rust because Phase 5B has not yet introduced a facade or Rust
  binding for these helpers; the rust-availability flag is recorded in
  the JSON artifact for context.

Benchmark script: `tests/perf/bench_git_query_ops.py`
(`just bench-git-query-ops`). Raw report:
`plans/202604/perf_artifacts/bench_git_query_ops_phase5a.json`.

Commands to reproduce:

```bash
just install
just bench-git-query-ops \
  --runs 200 --warmup 30 \
  --output plans/202604/perf_artifacts/bench_git_query_ops_phase5a.json
```

## GitQueryOpsMixin inventory

Every `@hookimpl` (and the one private parser) in
`src/sase/vcs_provider/plugins/_git_query_ops.py`, classified by Phase 5
disposition. Symbols are listed in source order.

### Class A — pure parser/normalizer (port to `sase.core` in Phase 5B–5D)

| symbol | shape | notes |
| --- | --- | --- |
| `_parse_git_name_status_z(stdout)` | `str -> list[(str, str)]` | The headline helper. Already a private function; trivially extractable. |
| inline parser inside `vcs_get_branch_name` | `str -> str \| None` | Strip newline; treat `""` and `"HEAD"` as detached. Phase 5B should expose as `parse_git_branch_name(stdout)`. |
| inline derivation inside `vcs_get_workspace_name` | `(str \| None, str \| None) -> str \| None` | Prefer remote URL basename without `.git`, else root path basename, else `None`. Phase 5B should expose as `derive_git_workspace_name(remote_url, root_path)`. |
| inline parser inside `vcs_get_conflicted_files` | `str -> list[str]` | Split on `\n`, drop blank lines. Phase 5B should expose as `parse_git_conflicted_files(stdout)`. |
| inline parser inside `vcs_has_local_changes` | `str -> str \| None` | Strip; empty -> `None`; non-empty -> the stripped string. Phase 5B should expose as `parse_git_local_changes(stdout)`. |

### Class B — pass-through command output (do **not** port)

| symbol | reason |
| --- | --- |
| `vcs_show_revision` | Returns the full diff/patch verbatim. No structure to parse. |
| `vcs_diff_with_untracked` | Concatenates tracked and per-file untracked diffs. Streaming/IO logic, not parsing. |
| `vcs_committed_diff` | Returns `git diff HEAD~1..HEAD` text verbatim. |
| `vcs_file_at_revision` | Returns file contents from `git show`. |
| `vcs_get_description` | Returns the commit message text from `git log --format=%B`. |

### Class C — host services / subprocess orchestration (do **not** port)

| symbol | reason |
| --- | --- |
| `vcs_resolve_revision` | Calls `git rev-parse` repeatedly, fetches from `origin`, falls back to `for-each-ref` glob. Subprocess + filesystem-aware. |
| `vcs_get_default_parent_revision` | Reads from `_get_default_branch` (Python state). |
| `vcs_diff_name_status` | The `git` invocation + error wiring. Calls `_parse_git_name_status_z` (Class A). |
| `vcs_is_sync_in_progress` | Inspects `.git/rebase-merge` / `.git/rebase-apply`. Filesystem state. |

### Class D — mutating / sync (do **not** port)

| symbol | reason |
| --- | --- |
| `vcs_sync_workspace` | `git fetch` + `git rebase`. Network + mutation. |
| `vcs_continue_sync`, `vcs_abort_sync` | `git rebase --continue/--abort`. Mutation. |
| `vcs_reword`, `vcs_reword_add_tag` | `git commit --amend`. Mutation. The reword/tag composition is a **single string concat** today (`f"{current_msg}\n{tag_name}={tag_value}"`) — not query-adjacent enough to justify a Rust port. |

### Class E — derivation / no-op stubs (do **not** port)

| symbol | reason |
| --- | --- |
| `vcs_derive_branch_name` | Wraps `strip_reverted_suffix` already in `sase.core.changespec`. Already routed through shared core. |
| `vcs_derive_branch_name_with_suffix` | Identity. |
| `vcs_can_rename_branch` | Constant `True`. |
| `vcs_get_bug_number`, `vcs_fix`, `vcs_upload` | Stubs returning fixed tuples for the bare-git contract. |

## Locked Phase 5 parser set

Phase 5B should produce a Python facade exposing exactly these helpers,
in this order of priority:

1. `parse_git_name_status_z(stdout: str) -> list[GitNameStatusEntryWire]`
   — the only helper with non-trivial parser logic and the only one with
   existing integration coverage
   (`tests/ace/deltas/test_diff_name_status_git.py`).
2. `parse_git_branch_name(stdout: str) -> str | None`.
3. `derive_git_workspace_name(remote_url: str | None, root_path: str | None) -> str | None`.
4. `parse_git_conflicted_files(stdout: str) -> list[str]`.
5. `parse_git_local_changes(stdout: str) -> str | None`.

Public facade output for `parse_git_name_status_z` should remain
`list[tuple[str, str]]` (rename/copy entries encoded as
`old\tnew`) so `vcs_diff_name_status` and the existing unit test do not
need to relax. The Rust binding can return `list[dict]` or a tuple
record; the Python facade hides that.

## Bench evidence

Median values; see the JSON artifact for min/p95/max and sample sizes
(200 runs / 30 warmup for synthetic and normalizer scenarios; 30 runs /
15 warmup for end-to-end git scenarios).

### Synthetic NUL streams (`parse_git_name_status_z`)

| workload | size (bytes) | entries (simple + rename) | median |
| --- | --- | --- | --- |
| `synthetic_small` | 1 255 | 50 + 5 | **9.7 µs** |
| `synthetic_medium` | 26 370 | 1 000 + 100 | **196 µs** |
| `synthetic_large` | 284 670 | 10 000 + 1 000 | **1.96 ms** |

Cost scales near-linearly with entry count, as expected for the current
single-pass split-and-walk implementation.

### Normalizers (single call timing the whole input)

| scenario | input | median |
| --- | --- | --- |
| `parse_git_branch_name_x4` | 4 stdouts (incl. `"HEAD\n"`, blank) | **0.59 µs** |
| `derive_git_workspace_name_x5` | 5 (URL, path) pairs | **1.60 µs** |
| `parse_git_conflicted_files_50` | 50-line stdout | **3.13 µs** |
| `parse_git_local_changes_150` | 150-line porcelain + empty | **0.31 µs** |

### End-to-end `git diff --name-status -z` on a temp repo

| workload | seeded files | stream size | `subprocess only` | `parse only` | `subprocess + parse` |
| --- | --- | --- | --- | --- | --- |
| `end_to_end_50` | 50 | 688 B | **2.96 ms** | 18 µs | **2.84 ms** (1) |
| `end_to_end_500` | 500 | 7 780 B | **11.0 ms** | 200 µs | **11.5 ms** |

(1) `subprocess + parse` < `subprocess only` at 50 files because each is
a separate timing batch; the difference is well inside the noise band
of a 30-iteration run.

### What this says about a Rust port

- At a typical PR-sized diff (~50 entries), parsing is ~18 µs while
  forking `git diff` is ~2.96 ms. **Subprocess is ~165× the parse
  cost.** Replacing the parser with a Rust implementation cannot move
  total wall-clock by more than ~0.6 % even at zero parse cost.
- At a deliberately large 500-file diff, the ratio narrows to ~55×,
  but the subprocess still dominates by nearly two orders of
  magnitude.
- The synthetic 10 000-entry workload is the only place where parsing
  reaches millisecond range. Real workloads of that size are extremely
  rare in this codebase's call sites (the Phase 5 plan calls the Git
  query surface "name-status diffs, branch names, conflict lists" —
  all single-digit-KB outputs in practice).
- The normalizers are sub-microsecond. PyO3 round-trip overhead alone
  would dwarf any Rust speedup.

The benchmark is not measuring "should we use Rust": it is the
documentation Phase 5F will need to record that the Rust port did
**not** save user-perceived time and should not be sold as if it did.

## Scoping for Phase 5

Confirms the Phase 5 plan as written:

- Move only the five helpers above to a `sase.core` facade.
- Keep `git` invocation, timeouts, fetch fallback, rebase state,
  conflict resolution, reword, sync, and all other Class B/C/D
  operations in Python. They are not moving to Rust this phase or any
  follow-on phase contemplated by the migration research.
- The Phase 5 plan's "exclude pass-through diff/content/message
  operations" line stands. None of `vcs_show_revision`,
  `vcs_diff_with_untracked`, `vcs_committed_diff`,
  `vcs_file_at_revision`, or `vcs_get_description` need Rust help.
- `vcs_reword_add_tag`'s tag-composition (`f"{msg}\n{tag}={value}"`)
  is too small to justify a separate `compose_commit_message_tag`
  helper. Leave it inline.
- Default backend stays `python`. Phase 5D should classify the new
  helpers as **shipped** Rust operations (raise
  `RustBackendUnavailableError` under `SASE_CORE_BACKEND=rust` if a
  binding is missing) — same posture as the parser/query/agent-scan
  helpers.
- `gix` is **out of scope** for the entire Phase 5 family. If the
  subprocess cost ever needs to be attacked, that is a separate plan
  (provisional working name "Phase 10: gix-backed Git provider"); do
  not silently fold it into Phase 5.

### Wire contract notes for Phase 5B

- `parse_git_name_status_z` may benefit from a tiny dataclass
  (`GitNameStatusEntryWire(status: str, path: str)`) on the wire side,
  but the **Python facade** must preserve `list[tuple[str, str]]`
  with the rename `old\tnew` encoding so
  `tests/ace/deltas/test_diff_name_status_git.py` and the upstream
  delta-mapping logic do not need to relax. Rename-entry shape:
  `("R100", "old\tnew")`. Test
  `test_parse_git_name_status_z_handles_renames_and_simple_entries`
  pins the contract today.
- `parse_git_branch_name` returns `None` on both `""` and `"HEAD"` to
  match the current `vcs_get_branch_name` `(True, None)` for detached
  HEAD. Phase 5B golden tests should cover `"main\n"`, `""`, `"HEAD\n"`,
  and a name with a slash (`"feat/x\n"`).
- `derive_git_workspace_name` priority is **remote URL first, root
  path second**. `.git` suffix is stripped only from the URL leg
  (matching today's Python behavior). Test cases should include
  `"git@github.com:org/repo.git"`, `"https://github.com/org/repo"`,
  `"/srv/git/bare/widget.git"`, an empty/None URL with a non-empty
  root path, and both inputs `None` (returns `None`).
- `parse_git_conflicted_files` splits on `\n` only (not `\r\n`); the
  helper is exercised by `git diff --name-only --diff-filter=U` which
  emits LF on every supported platform. Mirror the Python behavior
  exactly.
- `parse_git_local_changes` returns `None` for whitespace-only stdout
  and the **stripped** non-empty string otherwise.
  `vcs_has_local_changes` returns `(True, None)` for clean / `(True,
  text)` for dirty; the facade helper returns `None` / `text` and lets
  the Python wrapper add the success flag.

### Dual-run note

`SASE_CORE_DUAL_RUN=1` for these helpers is straightforward — they are
all pure functions of strings. The existing `sase.core.dual_run`
machinery is enough; no orchestrator-level parity dance like Phase 4E
needed.

## Risks visible from the bench

- **PyO3 string round-trip overhead.** The normalizers cost <2 µs in
  Python. A Rust-bound version that copies the input into Rust and the
  output back into Python is unlikely to win and may lose. Phase 5C
  should benchmark the bindings before claiming any speedup; the gate
  is parity, not speedup. Document this in the Phase 5C handoff.
- **`parse_git_name_status_z` allocates many small tuples.** At 10 000
  entries the Python implementation is ~2 ms — the only place in
  Phase 5 where parsing has triple-digit µs cost. A Rust port can
  amortize the per-entry allocation, but the result still has to land
  in a Python `list[tuple[str, str]]`, so the upper bound on the win
  is 2× at that size and ~0× at typical sizes.
- **Test data with hyphenated names** (`feat/x`, `pkg-1`) is fine, but
  any synthetic test that uses `spec_<N>` will trigger the
  `sase.core.changespec.has_suffix` regex if it ever flows back into
  the changespec machinery. Phase 5B's tests should stick to file-path
  shapes and avoid changespec-name shapes for clarity.

## Exit criteria check

- A focused Git query-op benchmark exists and is wired into the
  Justfile (`just bench-git-query-ops`).
- Pure parser cost is recorded separately from subprocess cost on
  realistic and stress workloads.
- The locked Phase 5 parser set is documented above (5 helpers).
- `gix` is explicitly out of scope and will not be revisited inside
  Phase 5.
- No production behavior is routed through new code yet.
- Recommendation: proceed with Phase 5B, motivated by shared-core
  hygiene; do not measure success in raw speedup.

## Next phase

Phase 5B (`sase-1a.2`) — implement the Python facade
(`src/sase/core/git_query_facade.py`), define any wire records
(`GitNameStatusEntryWire`), and write golden tests pinning the parser
contract for all five helpers. Do not import `sase_core_rs` yet. The
agent for 5B should read this handoff,
`plans/202604/rust_backend_phase5_git_query_ops.md`,
`sdd/research/202604/rust_backend_migration.md`, and
`docs/rust_backend.md` before editing.
