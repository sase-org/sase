# Apollo: Remote-Capable Agent Execution with Stable Project Identity

## Goal

Two items from Bryan's inbox, researched together because they are the same problem
seen from two angles:

1. **Apollo** — let SASE run agents on remote machines (a beefier dev box, a cloud
   droplet, a pool of workers) instead of only the laptop the TUI runs on.
2. **Project aliases** — solve the "duplicate GitHub repo identity" problem so the
   same logical project has one stable name no matter where its bytes live.

These belong in one memo because **remote execution is impossible without stable,
location-independent project identity.** The moment an agent runs on a different
host, "the project" can no longer be "whatever is in this directory." It has to be a
name that resolves to the same logical project on the laptop, on the remote box, and
in the `~/.sase/` metadata that ties them together. Project aliases (just shipped as
the `sase-4c` epic) plus owner-qualified GitHub ids (designed but not yet built, see
[`same_named_github_repos.md`](../202605/same_named_github_repos.md)) are exactly that
identity layer.

This memo is research and design only. It proposes no code.

## TL;DR

- "Remote machine" for SASE decomposes into six concerns: **workspace allocation,
  command execution, logs, artifacts, credentials, and synchronization.** Each maps
  to an existing local abstraction that today hard-codes "local filesystem +
  `subprocess` + `cwd`."
- The cleanest integration point is **a new `apollo` workspace provider plugin** plus
  **a thin execution-transport seam** at agent launch. Apollo should *wrap* existing
  providers, not replace them: it allocates a remote workspace using the same
  bare-git / GitHub plumbing, then forwards command execution over a transport (SSH
  first) while keeping `~/.sase/` metadata authoritative on the controller.
- Stable project identity is the prerequisite. Finish the **Option A flat
  owner-qualified id** (`bbugyi200__zorg`) from the same-named-repos research, and
  treat **project aliases as the human-facing shorthand** that already canonicalizes
  at the launch boundary. Then identity is a string that resolves identically on
  every host.
- Architecture should be **staged so each step is testable locally before any real
  remote host exists**: (0) identity hardening, (1) a `local-loopback` Apollo
  transport that "remotes" to localhost, (2) SSH transport to a single static host,
  (3) a host pool with scheduling and the cross-machine coordinator from the
  multi-machine-sync research.

## Background: What SASE Assumes Today (all local)

Four subsystems were read for this memo. Every one of them assumes the agent, its
workspace, and the controlling TUI share one filesystem and one process namespace.

### Workspace provider (`src/sase/workspace_provider/`)

- Pluggy-based. Plugins register on the `sase_workspace` entry-point group
  (`pyproject.toml`); the hook contract is `WorkspaceHookSpec` in
  `src/sase/workspace_provider/_hookspec.py`. The manager registers **all** plugins
  and uses `firstresult=True` so the first plugin that claims a ref wins
  (`_plugin_manager.py`, `_registry.py`).
- Key hooks: `ws_resolve_ref(ref, workflow_type) -> ResolvedRef`,
  `ws_get_workspace_directory(workflow_type, workspace_num, project_name,
  primary_workspace_dir) -> str`, and `ws_get_workspace_name(cwd) -> str`.
- Allocation is **local git clones in numbered directories**. `WorkspaceStore.resolve()`
  (`store.py`) produces a `WorkspacePath` whose `checkout_dir` is a local path like
  `<basename>_<num>/`; `ensure_workspace_checkout()` / `_ensure_git_clone_at()`
  (`utils.py`) run `git clone <local-primary> <local-target>` with `subprocess` and a
  local `cwd`. The numbered `sase_<N>` workspaces are local clones, full stop.
- Two in-repo plugins: `bare_git_workspace` (git with a local bare origin) and
  `cd_workspace` (a non-VCS directory used as-is). The `sase-github` sibling repo adds
  a `gh` workspace plugin (`workspace_plugin.py`) that clones
  `~/projects/github/<owner>/<repo>/`.

### VCS provider (`src/sase/vcs_provider/`)

- Separate pluggy group `sase_vcs`; ABC `VCSProvider` in `_base.py`. Every method
  takes a `cwd: str` and shells out with `subprocess.run(..., cwd=cwd)`. Providers:
  `bare_git` (in-repo) and `github` (in `sase-github/plugin.py`).
- **Repo identity is derived at runtime from `git config --get remote.origin.url`.**
  `vcs_classify_repo()` claims a checkout for GitHub if the origin URL contains
  `github.com`. The `gh` CLI then infers owner/repo from that same local checkout.
  There is no durable, stored repo identity — it is recomputed from whatever the
  local `.git` says.

### Agent launch (`src/sase/agent/`)

- `execute_launch_plan()` (`launch_executor.py`) →
  `spawn_slot_with_workspace_retry()` (`launch_executor_workspace.py`) →
  `spawn_agent_subprocess()` (`launch_spawn.py`). Preparation and spawn are
  Rust-backed (`prepare_agent_launch` / `spawn_prepared_agent_process` via
  `sase_core_rs`).
- The agent is a **detached local `subprocess.Popen`** running
  `sase.axe.run_agent_runner` with `cwd` set to the workspace dir. Environment is
  scrubbed of stale parent vars and augmented with `extra_env`.
- Runtimes (Claude/Gemini/Codex/…) are pluggy `sase_llm` providers. The Claude
  provider shells out to the **`claude` CLI** with the prompt on stdin; **auth is
  whatever `claude login` left in the environment/home dir** — there is no explicit
  key passing.
- Artifacts: `~/.sase/projects/<project>/artifacts/<workflow>/<timestamp>/`. Output
  logs: `~/.sase/workflows/...` (sharded by month). Chat transcripts:
  `~/.sase/chats/<host>-<agent>-<ts>.md`.
- Coordination: workspace claims via Rust bindings (`claim_workspace`,
  `transfer_workspace_claim`, `release_workspace`) recorded in the project file's
  `RUNNING:` field; liveness via local PID checks (`is_process_alive`). **All of this
  assumes one machine sees all running agents.**

### Project identity & aliases (`src/sase/project_aliases.py`, `sase-4c`)

- A "project" is a directory under `~/.sase/projects/<name>/` holding `<name>.sase`
  (or legacy `.gp`). Identity is inferred from `cwd` via
  `infer_project_name_from_cwd()` (checkout marker → `ws_get_workspace_name()` hook →
  scan of `~/.sase/projects/`).
- **Project aliases just shipped.** `PROJECT_ALIASES:` header field, `aliases` on
  `ProjectRecordWire`, CLI `sase project alias {list,add,remove,clear}`, an ACE modal
  editor, and `canonicalize_project_aliases_in_prompt()` which rewrites
  `#gh:bob` → `#gh:bob-cli` **at the launch boundary** before xprompt expansion, VCS
  resolution, and artifact writes. Aliases are display/ergonomic only; they never
  become the storage key.
- **The duplicate-repo problem is not yet solved.** Per
  [`same_named_github_repos.md`](../202605/same_named_github_repos.md), `zettel-org/zorg`
  and `bbugyi200/zorg` both collapse to `~/.sase/projects/zorg/` and collide. The
  recommended fix is Option A: a **flat owner-qualified id** (`zettel-org__zorg`) used
  as the durable key everywhere, with short refs resolved via the alias map. Aliases
  are the prerequisite that landed; owner-qualification is the next step.

## Part 1 — What "Remote Machine" Means for SASE

"Run an agent on a remote machine" is not one feature. It is six concerns, each of
which currently has a local-only implementation. Apollo's job is to put a seam in each.

### 1.1 Workspace allocation

**Today:** `ws_get_workspace_directory()` clones a local numbered directory.

**Remote:** the workspace must be materialized **on the remote host's filesystem**, and
the controller must hold a *handle* to it (host + path + workspace number) rather than
a local path it can `os.listdir()`. Two sub-decisions:

- **Where the bytes come from.** Cleanest is to keep the bare/canonical repo as the
  source of truth and have the *remote* host clone from it — either by pushing the
  bare repo to the remote, or by having the remote clone from a reachable git URL
  (GitHub origin, or the controller exposed over SSH). The GitHub case is easiest:
  the remote already has network access to `github.com`, so a remote
  `git clone git@github.com:owner/repo` reproduces the same workspace with no byte
  transfer from the laptop.
- **Numbering and claims.** The `<basename>_<num>` scheme and the `RUNNING:` claim
  table must become **host-aware**. A claim is no longer "workspace 12 is busy" but
  "workspace 12 on host `apollo-1` is busy." This is the same coordination gap the
  multi-machine-sync research flagged; see §4.4.

### 1.2 Command execution

**Today:** `subprocess.Popen([...], cwd=workspace_dir)` locally; VCS ops are
`subprocess.run(..., cwd=cwd)`.

**Remote:** every place that runs a process in the workspace needs a **transport
indirection** — "run this argv, with this env, in this cwd, on this host, streaming
stdout/stderr back." For SSH that is `ssh host 'cd <dir> && env … <argv>'`. The hard
part is not the happy path; it is that today these `subprocess` calls are scattered
across the VCS provider, the workspace provider, and the agent runner. Apollo needs
**one execution interface** that local and remote both implement, so callers stop
calling `subprocess` directly. (See §3.2 — this is the single most invasive change and
the reason for staging.)

### 1.3 Logs

**Today:** output logs at `~/.sase/workflows/...`, chat transcripts at
`~/.sase/chats/...`, both on the controller's disk where the TUI reads them.

**Remote:** the agent's stdout/stderr originate on the remote host. Options:

- **Stream-through:** the transport pipes remote stdout back to the controller, which
  writes the log locally exactly as today. Simplest; keeps the TUI unchanged; the log
  lives where the TUI already looks. Preferred for the first stages.
- **Write-remote-then-sync:** the agent writes logs on the remote host and a sync
  layer (multi-machine-sync) ships them back. Lower coupling but adds latency and a
  sync dependency.

Chat transcripts are already `<host>-<agent>-<ts>.md`, so remote-origin chats never
collide with local ones — the naming was forward-compatible by luck.

### 1.4 Artifacts

**Today:** `~/.sase/projects/<project>/artifacts/<workflow>/<timestamp>/`, scanned by
the TUI's agent listing (Rust-backed `scan_agent_artifacts`).

**Remote:** artifacts are produced on the remote host but the **TUI scans the
controller's filesystem.** Two viable models:

- **Controller-authoritative metadata, remote-authoritative blobs.** Small status
  files (`agent_meta.json`, `done.json`, `running.json`, plan/question markers) are
  written or mirrored to the controller so the existing scan works unmodified; large
  blobs (diffs, generated files, screenshots) stay remote and are fetched on demand.
  This matches the multi-machine-sync bucketing (small text = sync; large blobs =
  object storage / fetch-on-demand) and is the recommended split.
- **Full artifact sync.** Simpler conceptually, heavier operationally; rejected as a
  default for the same volume reasons the sync research documented (22k chat files,
  multi-GiB log trees).

### 1.5 Credentials

**Today:** the Claude provider relies on ambient `claude login` state; `gh`/git rely
on the user's local SSH keys and `gh auth`. Nothing is passed explicitly.

**Remote:** this is the thorniest concern and deserves an explicit policy decision (see
open questions). The realistic stance for early stages is **"the remote host is
pre-provisioned and self-credentialed"**: the remote already has `claude login`, `gh
auth`, and an SSH key for git. The controller forwards *no* secrets; it only forwards
the prompt and non-secret env. This keeps Apollo out of the secret-management business
initially. Forwarding (SSH agent forwarding, short-lived tokens, a secrets broker) is a
later stage and should not block the first remote run.

### 1.6 Synchronization

**Today:** none needed — one filesystem.

**Remote:** the controller's `~/.sase/` and the remote host's working state must stay
coherent. This memo deliberately **reuses the multi-machine-sync design** rather than
re-deriving it: per-domain hybrid (Syncthing/object storage for chats+artifacts,
per-project git for ChangeSpecs, never-sync for ephemeral/lock/log state) plus a small
coordinator for claims. Apollo's contribution is to make the *agent* remote; the *state*
coherence is the sync research's problem, and the two should land as complementary
tracks. The coordinator (multi-machine-sync Phase 3) is the shared dependency: it is
what makes workspace claims and agent-name leases correct across hosts.

## Part 2 — Project Aliases and the Duplicate-Repo Problem

Remote execution multiplies the locations a project can live: laptop clone, remote-host
clone, bare repo, GitHub origin. If identity is "the repo basename" or "whatever
`remote.origin.url` says in this checkout," those locations fragment into colliding or
inconsistent project names. The fix is to make identity a **stable string that resolves
identically everywhere**, with aliases as the human shorthand.

### 2.1 The two layers, and why both are needed

- **Canonical id (storage key).** Per Option A of the same-named-repos research, a flat
  owner-qualified id like `bbugyi200__zorg`. This is the durable key for the project
  directory, `.sase`/archive files, `branch_map.json`, `RUNNING:` claims, ChangeSpec
  prefixes, and artifact roots. It is collision-proof by construction and — critically
  for Apollo — **derivable on any host from the GitHub remote alone**, with no
  dependence on local checkout path. Two hosts cloning `git@github.com:bbugyi200/zorg`
  independently compute the same id.
- **Aliases (human ref).** The shipped `sase-4c` machinery. `#gh:zorg` or `#gh:bob`
  canonicalizes to the qualified ref at the launch boundary before anything durable is
  written. This is what keeps remote launches ergonomic: a user types a short ref, and
  it resolves to the same canonical id whether the agent will run locally or on
  `apollo-1`.

The shipped aliases are the *prerequisite*; owner-qualification is the *missing half*.
Together they are the identity contract Apollo needs.

### 2.2 How aliases prevent duplicate identity across locations

| Location | Today (basename) | With qualified id + aliases |
| --- | --- | --- |
| Laptop clone `~/projects/github/bbugyi200/zorg/` | infers `zorg` | `ws_get_workspace_name()` parses remote → `bbugyi200__zorg` |
| Laptop clone `~/projects/github/zettel-org/zorg/` | infers `zorg` → **collides** | `zettel-org__zorg` — distinct, no collision |
| Bare repo `~/.sase/repos/zorg.git` | basename `zorg` | qualified id stored in project metadata, not re-derived from path |
| Remote host clone | would infer `zorg` again | same `bbugyi200__zorg` from the same GitHub remote |
| User-typed ref `#gh:zorg` | ambiguous | alias map resolves to the one match, or errors listing candidates |

The key property for remote work: **identity comes from the GitHub remote URL, not the
filesystem path.** Path-derived identity breaks the instant the path differs across
hosts; remote-URL-derived identity is stable across hosts by construction. The
qualified id is the same on the laptop and on `apollo-1` because both parse the same
`git@github.com:bbugyi200/zorg.git`.

### 2.3 Required work (mostly already specced)

The same-named-repos research already enumerates the implementation
(`parse_github_remote_url`, `github_project_id`, `ws_get_workspace_name()` for GitHub,
qualified ChangeSpec prefixes, migration from `remote.origin.url`, flat `__` separator
to keep existing globs working). Apollo does not change that plan; it **raises its
priority**, because remote execution is the use case that makes path-independent
identity non-optional rather than merely tidy. The one Apollo-specific addition: the
qualified id and its display name (`owner/repo`) should travel in the **remote launch
handle** so the remote host never has to re-derive identity from its own checkout path.

## Part 3 — How Apollo Integrates with Existing Providers

Design principle: **Apollo wraps, it does not fork.** A remote bare-git project and a
remote GitHub project are still bare-git and GitHub projects; only the *execution
location* changed. So Apollo should compose with the existing workspace/VCS plugins
rather than reimplement their logic for "remote."

### 3.1 An `apollo` workspace provider that delegates

Add an `apollo` plugin on the `sase_workspace` group that:

- Claims refs of a remote-qualified form (e.g. `#apollo:apollo-1:gh:bbugyi200/zorg`, or
  a config that marks a project as "runs on host X"), parses out **(target host, inner
  ref)**, and delegates the inner ref to the normal resolution path to get the
  canonical `ResolvedRef` (project name, primary dir, VCS workflow type).
- Implements `ws_get_workspace_directory()` by materializing the clone **on the remote
  host** (via the execution transport, §3.2) instead of locally, and returns a handle
  the rest of SASE treats as the workspace location. The numbered-clone scheme is reused
  verbatim — it just runs `git clone` over the transport on the remote's disk.
- Records the workspace in a **host-aware** registry/claim so `RUNNING:` and
  `sase workspace list` can show `#12@apollo-1`.

Because the plugin manager already uses `firstresult=True`, an `apollo` plugin slots in
ahead of the local plugins for remote refs and stays out of the way for local ones. No
change to the hook ABI is required for resolution; the `ResolvedRef.extra` dict (already
used for GitHub display metadata) can carry the target host.

### 3.2 The execution transport seam (the real work)

The invasive change is **introducing one execution interface** that both local and
remote implement, and routing today's scattered `subprocess` calls through it. Sketch:

- An `Executor` abstraction: `run(argv, *, cwd, env, stdin, stream) -> result`,
  with a `LocalExecutor` (today's `subprocess` behavior, byte-for-byte) and an
  `SshExecutor` (`ssh host 'cd cwd && env … argv'`, streaming back stdout/stderr).
- The VCS provider's `cwd`-keyed `subprocess.run` calls, the workspace provider's
  `git clone`/`git status` calls, and the agent runner's process spawn all take an
  `Executor` instead of calling `subprocess` directly. For local projects the executor
  is `LocalExecutor` and nothing observable changes.
- This is where the **Rust core boundary** matters. `prepare_agent_launch` /
  `spawn_prepared_agent_process` are Rust-backed, and per `rust_core_backend_boundary.md`
  shared backend behavior belongs in `../sase-core`. The execution-transport contract is
  exactly the kind of cross-frontend behavior (a web client or CLI would need the same
  "run an agent on host X" semantics) that should be modeled in the Rust core's launch
  wire, with Python/TUI calling through the binding. The transport *implementation* (SSH
  process management) can start in Python and migrate down once the contract proves out.

This seam is large enough that it must be staged, which is the whole point of Part 4:
the `LocalExecutor` refactor lands and is verified with zero behavior change *before* any
SSH code exists.

### 3.3 VCS provider: keep operations where the checkout is

The VCS provider already takes `cwd` on every method. The minimal remote story is: when
the checkout is remote, the `cwd` is a remote path and the provider runs through the
`SshExecutor`. GitHub identity (`remote.origin.url` → owner/repo, `gh` CLI context) then
works **on the remote host** with no parsing changes — the remote checkout has the same
origin as the laptop would have. This is a strong argument for the GitHub case being the
*first* remote target: it requires the least new identity plumbing because the remote can
self-derive everything from its own clone of the same GitHub repo.

## Part 4 — Staged Architecture (Local-Testable Before Remote)

The constraint "testable locally before true remote execution" drives the staging.
Every stage either changes nothing observable (refactors) or can be exercised with a
loopback transport on the developer's own machine.

### Stage 0 — Identity hardening (no Apollo code yet)

Land the Option A owner-qualified GitHub id on top of the shipped aliases:
`parse_github_remote_url`, `github_project_id`, GitHub `ws_get_workspace_name()`,
qualified ChangeSpec prefixes, and the migration command. Fully local, fully testable
with the existing same-named-repos test plan. **This unblocks everything else** because
it makes project identity host-independent. Without it, remote launches will collide
exactly as same-named local repos collide today.

### Stage 1 — `LocalExecutor` extraction + `local-loopback` transport

- Extract the `Executor` interface and route existing `subprocess` calls through
  `LocalExecutor`. Acceptance criterion: **no behavior change** — the full `just check`
  suite and the ACE PNG snapshot suite pass unchanged.
- Add a `local-loopback` Apollo transport whose "remote host" is `localhost` reached
  *through the same `Executor` interface* (optionally via a real `ssh localhost` to
  exercise the SSH code path without a second machine). Allocate a workspace, run an
  agent "remotely," stream logs back, scan artifacts. This proves the entire Apollo
  control flow — handles, host-aware claims, log stream-through, artifact mirroring —
  with no second machine and no new credentials.

This is the stage that delivers the "testable locally before true remote" guarantee.

### Stage 2 — SSH transport to one static host

- Implement `SshExecutor` against a single configured host that is **pre-provisioned
  and self-credentialed** (`claude login`, `gh auth`, git SSH key already present).
- Remote GitHub projects first (Stage 0 makes the remote self-derive identity). Clone on
  the remote from the GitHub origin; no byte transfer from the laptop.
- Logs stream through; small artifact/status files mirror to the controller so the
  existing TUI scan works; large blobs fetched on demand.
- Coordination still "one controller drives," documented as a constraint exactly as the
  multi-machine-sync Phase 1 does.

### Stage 3 — Host pool, scheduling, and the cross-machine coordinator

- Generalize one host to a pool with a placement policy (round-robin, least-loaded, or
  per-project pinning via config/aliases).
- Adopt the multi-machine-sync **Phase 3 coordinator** for host-aware workspace claims
  and TTL'd agent-name leases, so two controllers / many hosts cannot double-claim.
  This is the shared dependency that turns "one machine at a time" into real
  multi-host safety.
- Layer the sync research's per-domain hybrid for `~/.sase/` coherence so chats,
  artifacts, and ChangeSpecs produced remotely are durably reflected on the controller.

### Why this order

Each stage is independently valuable and independently testable. Stage 0 is pure local
correctness. Stage 1 is a pure refactor with a loopback proof. Stage 2 is the first real
remote run but with the credential and coordination problems deliberately deferred by
constraint. Stage 3 takes on the genuinely distributed problems only once the execution
seam is proven. Nothing forces the hard problems (secret forwarding, distributed
locking, full state sync) to be solved before the first remote agent runs.

## Risks and Open Questions

- **Credential policy is the biggest unknown.** The "remote is self-credentialed"
  stance unblocks early stages but does not scale to ephemeral cloud workers that need
  fresh `claude`/`gh`/git auth per boot. Decision needed before Stage 3: SSH agent
  forwarding vs. short-lived tokens vs. a secrets broker. Out of scope for Stage 0–2.
- **The `Executor` refactor touches many call sites.** VCS provider, workspace provider,
  and agent runner all shell out independently. The risk is a subtle behavior change in
  the `LocalExecutor` path; mitigation is the zero-diff acceptance criterion plus the
  PNG/`just check` suites.
- **Rust boundary placement.** The launch/spawn path is already Rust-backed. Decide
  early whether the transport contract lives in `../sase-core` (correct per the boundary
  rule, since web/CLI frontends would need it) or starts in Python and migrates. Getting
  this wrong means reworking the wire contract.
- **Claim and lease correctness across hosts** is the same catastrophic-if-wrong concern
  the sync research flagged (`agent_name_allocation.lock` is `fcntl.flock` on a local
  file — syncing it does not make it distributed). Stage 3 must not ship without the
  coordinator.
- **Artifact scan assumes a local filesystem.** The Rust `scan_agent_artifacts` path
  walks `~/.sase/projects/*/artifacts/`. The "mirror small status files" approach keeps
  it working unmodified; if that proves insufficient, the scan itself becomes
  host-aware, which is a larger change.
- **Naming.** "Apollo" is a fresh codename from the inbox; `grep -ri apollo` over the
  repo and `sdd/` returns nothing today. Pick the user-facing surface (`#apollo:host:…`
  ref form? a `sase apollo` command group? a per-project `RUN_HOST:` field?) before
  Stage 1 so the loopback transport models the real ergonomics.

## Relationship to Existing Research

- [`same_named_github_repos.md`](../202605/same_named_github_repos.md) — the identity
  design this memo's Stage 0 adopts wholesale. Apollo is the use case that makes its
  Option A non-optional.
- [`multi_machine_sync.md`](../202605/multi_machine_sync.md) — the state-coherence and
  coordinator design this memo reuses rather than re-deriving. Apollo makes the *agent*
  remote; that research makes the *state* coherent. They are complementary tracks that
  share the Stage 3 coordinator dependency.
- [`textual_serve_ace_web_access.md`](../202605/textual_serve_ace_web_access.md) and the
  web-client research — a future web frontend wants the same "run on host X" semantics,
  reinforcing the argument to model the execution transport in the Rust core.
