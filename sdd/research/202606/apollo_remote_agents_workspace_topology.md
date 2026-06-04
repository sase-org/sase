# Apollo Remote Agents, Workspace Topology, And Project Aliases

Date: 2026-06-04
Status: consolidated research/design memo

## Question

How should SASE use Apollo to run agents on remote machines while keeping one stable project identity for a GitHub
repository across local paths, bare repos, and remote hosts?

This memo consolidates the two prior research notes:

- `apollo_remote_agents_and_project_identity.md`
- `apollo_remote_agents_project_aliases.md`

Both notes found the same core issue: remote execution and duplicate GitHub project identity are one design problem.
Once an agent can run on another host, a project cannot be identified by the controller's current directory, a local
`WORKSPACE_DIR`, or the repo basename. SASE needs a provider-normalized project identity first, and Apollo should run
work against host-local checkouts selected by that identity.

`Apollo` appears only in the inbox research prompt and generated research notes. There is no existing Apollo API or
implementation in the SASE or `sase-github` code read for this memo, so the design below describes the SASE-side
contract Apollo should satisfy.

## Summary

SASE is local-only today:

- workspace providers return local paths in `ResolvedRef`;
- `WorkspaceStore` materializes local git clones and records a local registry;
- the launch path preclaims a ProjectSpec `RUNNING` slot, spawns a detached local runner, and transfers the claim to a
  local PID;
- the runner writes artifacts and logs under the local SASE home, changes directory into a local checkout, and invokes
  local provider CLIs;
- VCS and LLM providers shell out through local `subprocess` calls;
- project aliases rewrite human refs, but they do not define provider-normalized repository identity.

The recommended architecture is:

1. Add stable project identity before true remote execution.
2. Treat Apollo primarily as an execution provider around agent launch.
3. Keep existing workspace/VCS providers responsible for ref semantics, but derive a remote materialization plan from
   them instead of trusting their local checkout paths.
4. Start the whole SASE runner on the execution host, not individual nested shell commands from a local runner.
5. Mirror or stream logs and artifact metadata back to the controller.
6. Use local simulation and loopback Apollo before SSH or true remote hosts.

The one conflict between the prior notes was the Apollo boundary. One note proposed an `apollo` workspace provider; the
other argued Apollo should not be a workspace provider. The consolidated position is:

- Apollo should not replace `#gh`, `#git`, or `#cd` provider semantics.
- Apollo may expose a thin target-selection wrapper, such as config, a launch flag, or a remote-qualified ref form.
- The durable boundary should be an execution/remote-workspace allocator that wraps provider-derived materialization
  plans and returns host-qualified leases and process handles.

## Evidence From Current Code

Primary sources checked:

- Workspace provider contract and local materialization:
  - `src/sase/workspace_provider/_hookspec.py`
  - `src/sase/workspace_provider/store.py`
  - `src/sase/workspace_provider/utils.py`
  - `src/sase/workspace_provider/registry.py`
  - `src/sase/workspace_provider/plugins/bare_git_ref.py`
  - `src/sase/workspace_provider/plugins/bare_git_workspace.py`
  - `src/sase/workspace_provider/plugins/cd_workspace.py`
  - `docs/workspace.md`
- GitHub provider and VCS workflow:
  - `/home/bryan/.local/state/sase/workspaces/sase-org/sase-github/sase-github_11/src/sase_github/workspace_plugin.py`
  - `/home/bryan/.local/state/sase/workspaces/sase-org/sase-github/sase-github_11/src/sase_github/plugin.py`
  - `src/sase/vcs_provider/_command_runner.py`
  - `src/sase/vcs_provider/plugins/_git_core_ops.py`
  - `docs/vcs.md`
- Project aliases and lifecycle:
  - `src/sase/project_aliases.py`
  - `sdd/epics/202606/project_aliases.md`
  - `sdd/research/202605/same_named_github_repos.md`
- Launch, runner, artifacts, and claims:
  - `src/sase/agent/launch_executor_workspace.py`
  - `src/sase/agent/launch_spawn.py`
  - `src/sase/core/agent_launch_wire.py`
  - `src/sase/running_field/_workspace.py`
  - `src/sase/running_field/_operations.py`
  - `src/sase/running_field/_model.py`
  - `src/sase/axe/run_agent_runner.py`
  - `src/sase/axe/run_agent_runner_setup.py`
  - `src/sase/axe/run_agent_runner_finalize.py`
  - `src/sase/axe/run_agent_phases.py`
  - `src/sase/artifacts.py`
- Cross-machine and sibling context:
  - `src/sase/sibling_repos.py`
  - `sdd/research/202605/multi_machine_sync.md`
  - `memory/short/rust_core_backend_boundary.md`

## Current Topology

### Workspace Providers

The workspace hook contract returns:

```text
ResolvedRef(
  project_file,
  project_name,
  primary_workspace_dir,
  checkout_target,
  extra,
)
```

Every required path in that shape is local. `primary_workspace_dir` is the controller's checkout path, and
`ws_get_workspace_directory()` returns or materializes a controller-local checkout path.

`WorkspaceStore` adds a better local layout model than legacy string suffixing. It supports `xdg-state`, `adjacent`, and
absolute workspace roots, with `SASE_WORKSPACE_ROOT` as an override. It also derives a `project_key` from a single git
remote when available, otherwise from a path hash. That is useful precedent, but it is still a local checkout namespace,
not a cross-host project identity or execution lease.

The managed workspace registry records local fields such as `checkout_dir`, `materialization`, `role`, timestamps,
pinning, and generation. It does not record `host_id`, remote transport, credential state, execution handles, or a
provider-normalized repository identity.

### GitHub Resolution

The GitHub workspace plugin preserves owner in the clone path:

```text
~/projects/github/<owner>/<repo>/
```

but drops owner from the ProjectSpec key:

```text
~/.sase/projects/<repo>/<repo>.sase
```

For `#gh:owner/repo`, `resolve_gh_ref()` derives `project_name=<repo>` and writes `WORKSPACE_DIR` to the basename
ProjectSpec. This is the duplicate identity risk. Two GitHub repos with the same repo name but different owners collide
in SASE metadata even though their checkout paths differ.

The May same-named repo research already identifies the correct base fix: use an owner-qualified flat project id such
as `bbugyi200__zorg`, keep `owner/repo` as display metadata, and use aliases for ergonomic short refs.

### Bare Git And Directory Workspaces

Bare-git resolution has the same identity issue in local form. A bare repo path containing `/` derives the project name
from the path basename and stores local `BARE_REPO_DIR` and `WORKSPACE_DIR` fields. That works on one host, but it does
not prove that two hosts' `foo.git` paths refer to the same repository.

`#cd` is explicitly path-based and local. It should be local-only unless Apollo later supports configured path mappings
or shared mounts.

### Project Aliases

Project aliases are stored as ProjectSpec metadata and loaded through `src/sase/project_aliases.py`. They rewrite prompt
refs at the launch boundary before xprompt expansion and durable artifact writes. They also reject alias collisions with
real project names and with other aliases.

Current alias behavior is correct but limited:

- aliases map a short human ref to a canonical SASE project name;
- alias canonicalization skips refs containing `/`;
- aliases do not index GitHub owner/repo identity;
- aliases do not migrate existing basename project records.

So aliases solve `#gh:bob -> #gh:bob-cli`, but they do not by themselves solve
`#gh:bbugyi200/bob-cli`, `/some/checkout/bob-cli`, and a remote host checkout all mapping to one project.

### Launch, Claims, And Runner

Regular non-home launches preclaim a workspace from the ProjectSpec `RUNNING` field, resolve a local workspace directory,
spawn a detached local subprocess, and transfer the claim to the child PID.

Important local assumptions:

- `RUNNING` entries are `#N | PID | workflow | cl_name | timestamp`.
- `WorkspaceClaimRequestWire` carries a local PID and optional transfer-from PID.
- `AgentLaunchRequestWire` carries local `project_file`, `workspace_dir`, and `workspace_num`.
- `spawn_agent_subprocess()` calls Rust-backed `spawn_prepared_agent_process()` and receives a local PID.
- liveness, chop, kill, and release logic expect local process semantics.

The runner starts on the same machine, reads the local prompt file, writes artifacts under local `~/.sase/projects`, then
`chdir`s into the local workspace. It prepares the workspace, invokes LLM providers, writes `agent_meta.json`,
`workflow_state.json`, `done.json`, notifications, logs, and finally releases the local workspace claim.

LLM providers are also local. Claude invokes the `claude` CLI; Codex invokes `codex exec` with a SASE-managed local
Codex home. VCS providers and workspace materialization shell out locally through `subprocess` or the VCS
`CommandRunner`.

## What A Remote Machine Means For SASE

A remote machine is an execution host, not just another checkout path. It has its own filesystem, process namespace,
installed tools, credentials, SASE runtime, workspace root, and logs. The controller may remain the TUI/CLI process
where the user watches status and artifacts.

Remote support breaks into six surfaces.

### 1. Workspace Allocation

Current allocation returns a workspace number and local path. Remote allocation should return a host-qualified lease:

```text
canonical_project_id
workflow_type
checkout_target
host_id
workspace_num
host_workspace_dir
lease_token
lease_epoch
materialization_generation
```

Keep workspace numbers global per canonical project for the first remote-capable version. The display can show
`#17@apollo-1`, but the controller should still allocate one namespace for a project until UI, retry, artifact, and
ChangeSpec lookup paths are explicitly host-scoped.

Workspace directories are host-local. A host workspace registry can map:

```text
(host_id, canonical_project_id, workspace_num) -> host-local checkout path
```

ProjectSpec identity must not depend on that path.

### 2. Command Execution

The most coherent remote unit is the whole runner process:

```text
python -m sase.axe.run_agent_runner ...
```

Running individual nested commands remotely from a local runner would leak too many assumptions: cwd mutation,
provider CLI auth, signal handling, interrupt flow, artifact writes, deferred workspace claiming, and environment
setup.

Apollo should therefore start the runner on the execution host and return a process handle. Supporting command
execution is still needed for preflight, materialization, status, kill, and artifact transfer, but the controller should
not try to execute every VCS/LLM step remotely one subprocess at a time.

### 3. Logs

There are two log classes:

- live output that the TUI/status/revive paths need;
- heavy host diagnostics such as provider debug logs, hook logs, perf traces, and support data.

Live output should stream through Apollo or mirror into the controller's SASE home using the run id. Heavy diagnostics
should remain host-local by default and be collected explicitly through a future support bundle command. This matches
the multi-machine sync finding that runtime logs can dwarf all other state.

### 4. Artifacts

The current TUI scans local project artifacts under:

```text
~/.sase/projects/<project>/artifacts/<workflow>/<timestamp>/
```

For remote agents, artifact identity should be independent of host-local path:

```text
canonical_project_id
workflow_name
run_id or timestamp
host_id
workspace_num
```

The first bridge should mirror small, user-facing artifact metadata back to the controller:

- `agent_meta.json`
- `workflow_state.json`
- `running.json`
- `done.json`
- plan/question markers
- explicit user artifacts or indexed references

Large blobs and heavy diagnostics can remain remote with fetch-on-demand. Active runs need heartbeat and sync status so
the controller can distinguish running, stale, failed, and unsynced states.

### 5. Credentials

Early Apollo should assume the execution host is self-credentialed:

- SASE installed at a compatible version;
- provider plugins installed;
- `git`, `gh`, `claude`, `codex`, or other required CLIs available;
- GitHub/git/LLM auth already configured on that host;
- network access to the canonical repo remote;
- enough disk and an allowed workspace root.

Apollo should not copy SSH keys, GitHub tokens, Claude/Codex auth, or provider config by default. Secret forwarding can
be a later explicit Apollo capability with audit logs and narrow lifetimes.

### 6. Synchronization

There are three sync problems:

1. source code;
2. SASE control state;
3. logs and artifacts.

Source code should sync through real VCS remotes whenever possible. GitHub is the best first remote target because
`owner/repo` gives a network-reachable materialization source. Local bare repos need either a declared network remote or
a clear "local-only" failure before Apollo launch.

SASE state should reuse the multi-machine sync research rather than inventing a second model. Immutable or append-mostly
artifacts and chats can sync or mirror. Runtime locks, PID files, huge logs, local workspaces, and local daemon state
should not be synced as shared truth. Cross-host correctness eventually needs a coordinator with leases and fencing.

## Stable Project Identity

Remote execution requires separating concepts that are currently conflated:

| Concept | Purpose | Example |
| --- | --- | --- |
| Canonical project id | Durable SASE storage key | `bbugyi200__bob-cli` |
| Provider remote identity | Normalized repo identity | `github:bbugyi200/bob-cli` |
| Display name | Human label | `bbugyi200/bob-cli` |
| Alias | User shorthand | `bob` |
| Host checkout path | Per-host filesystem path | `/home/bryan/projects/github/bbugyi200/bob-cli` |

For GitHub, use the May same-named repo recommendation:

```text
canonical_project_id = github_project_id(owner, repo)
display_name = owner/repo
remote_identity = github:lowercase-owner/lowercase-repo
```

The exact ProjectSpec field names can change, but the record needs enough metadata to build a remote-identity index:

```text
PROJECT_ID: bbugyi200__bob-cli
PROJECT_DISPLAY_NAME: bbugyi200/bob-cli
PROJECT_REMOTE_ID: github:bbugyi200/bob-cli
PROJECT_ALIASES: bob
```

Resolver behavior should be:

1. Canonicalize explicit aliases as today.
2. Normalize provider refs with remote identity, such as `#gh:owner/repo`.
3. Look up existing ProjectSpecs by `PROJECT_REMOTE_ID` before creating metadata.
4. If exactly one project matches, route to its canonical id.
5. If none matches, create a ProjectSpec using the canonical provider id and persist remote metadata.
6. For short refs such as `#gh:repo`, first apply explicit aliases, then resolve only if exactly one known GitHub repo
   has that short repo name. Otherwise return an ambiguity error listing owner/repo candidates.
7. For local path or bare repo refs, parse the repo remote when available. If it maps to an existing remote identity,
   attach to that project. If it has no remote identity, keep it host-local unless the user publishes it or declares an
   explicit identity.

This prevents these forms from becoming separate projects when they refer to the same repo:

```text
#gh:bob
#gh:bob-cli
#gh:bbugyi200/bob-cli
/home/bryan/projects/github/bbugyi200/bob-cli
/remote/dev/projects/bob-cli
```

The migration base should remain the May same-named repo plan:

- flat owner-qualified ids, not nested `owner/repo` storage paths;
- display metadata separate from storage keys;
- owner-aware GitHub `ws_get_workspace_name()`;
- remote URL parsing preferred over checkout-path inference;
- qualified ChangeSpec prefixes if global ChangeSpec lookup remains name-only;
- refuse migration while legacy projects have active `RUNNING` claims;
- avoid rewriting completed historical artifacts unless active/resumable state requires it.

Remote execution adds one constraint: do not migrate host-local checkout paths into global identity fields. Paths belong
in host workspace registries or launch handles.

## Apollo Integration

Apollo should wrap existing providers at the launch/execution boundary.

The target launch pipeline should be:

1. Canonicalize project aliases.
2. Resolve the workspace ref enough to identify the canonical project and provider semantics.
3. Convert the resolved ref into a remote materialization plan.
4. Ask the execution provider for a host-qualified workspace lease.
5. Start the runner through the execution provider.
6. Stream or mirror logs and artifacts.
7. Record a host-qualified process handle.

The local execution provider can keep today's behavior:

```text
claim_next_axe_workspace -> get_workspace_directory -> spawn_agent_subprocess -> local PID
```

The Apollo provider should:

- select or accept `host_id`;
- preflight host capabilities and credentials;
- materialize the checkout on that host;
- create or sync the needed SASE home subset;
- start the runner remotely;
- return a remote handle;
- heartbeat the lease;
- support status and kill through the handle;
- mirror artifact metadata and live output back to the controller.

### Materialization Plan

Current workspace hooks return local paths. Apollo needs a provider-neutral plan that can be executed on another host:

```text
canonical_project_id
project_display_name
workflow_type
vcs_family
vcs_provider_name
remote_identity
clone_url or fetch_url
checkout_target
setup_workflow
provider_extra
```

The local adapter can derive this plan from existing `ResolvedRef` and continue to call
`ws_get_workspace_directory()`. The Apollo adapter can send the plan to a remote host and let that host's workspace
store choose the host-local path.

Remote capability by provider:

- GitHub: best first target because `owner/repo` can be cloned or fetched on the execution host.
- Bare git: remote-capable only when there is a declared network-reachable remote or explicit publish step.
- `cd`: local-only unless configured path mapping or shared mounts are added.
- sibling repos: currently path-based and workspace-number based; remote support should resolve siblings by canonical
  identity and host-local materialization, with path-only siblings remaining local-only.

### Process Handles

`RUNNING` and live-agent metadata should stop treating PID as globally unique. A remote-capable handle needs:

```text
run_id
host_id
workspace_num
execution_provider
remote_pid or provider_process_id
lease_token
last_heartbeat_at
artifact_root_controller
artifact_root_host
log_stream_id
```

The local provider can populate `host_id` with the local machine id and `remote_pid` with the local PID. This lets the
schema become remote-ready before execution behavior changes.

Per the Rust core boundary guidance, the shared handle and launch wire should be modeled in `../sase-core` once the
shape is chosen, with Python acting as glue for the first transport implementation if needed.

### Control Host State

The current runner expects a local `project_file` and SASE home. There are two staged bridges:

1. Mirrored SASE home subset.
   - Sync the target ProjectSpec, config, and needed indexes to the execution host before launch.
   - Let the remote runner use existing `ProjectSpec` file paths.
   - Do not treat synced locks or PIDs as distributed locks.
2. Control-owned state with serialized runner input.
   - Controller resolves and locks project state.
   - Remote runner receives a snapshot and emits state-change events.
   - More correct long term, but a larger refactor.

Use the mirrored subset for local-first and first remote stages. Move toward control-owned transactions or an Apollo
coordinator when multiple controllers or host pools become real.

## Staged Architecture

### Stage 0: Identity Hardening

No Apollo execution yet.

- Land canonical GitHub project ids on top of shipped aliases.
- Add provider remote identity metadata and lookup.
- Add owner-aware GitHub workspace-name detection.
- Keep `WORKSPACE_DIR` as a host-local convenience path.
- Add tests for same repo via alias, owner/repo, local checkout path, and duplicate repo basename under two owners.

Acceptance checks:

- `#gh:bob`, `#gh:bob-cli`, and `#gh:bbugyi200/bob-cli` route to one canonical project when configured that way.
- `zettel-org/zorg` and `bbugyi200/zorg` create distinct ProjectSpecs.
- ambiguous `#gh:zorg` fails unless an explicit alias chooses one.

### Stage 1: Local Execution Handle

Keep behavior local.

- Add an execution-provider shape around current claim, workspace directory, spawn, and release logic.
- Extend launch/artifact metadata with `host_id + pid` handle fields.
- Keep current local PID behavior for compatibility.
- Route new code paths through the handle rather than raw PID where practical.

Acceptance check: local agent launches produce the same artifacts and behavior, but metadata can represent a
host-qualified process.

### Stage 2: Fake Hosts And Host-Scoped Workspace Roots

Still no true remote machine.

- Create two local fake hosts with different machine ids and workspace roots.
- Materialize the same canonical project under both roots.
- Store leases as `(host_id, canonical_project_id, workspace_num)`.
- Keep one controller-owned workspace number allocator.
- Exercise sibling repo resolution through host-local materialization rules.

Acceptance checks:

- fake host A and fake host B use different checkout paths without duplicate ProjectSpecs;
- artifacts record selected host;
- stale local PID checks do not classify fake remote handles as local live processes.

### Stage 3: Artifact And Log Mirroring

Run locally, but make artifact topology remote-ready.

- Let the fake remote runner write under a host-local artifact root.
- Mirror status files and indexed user artifacts back to the controller project tree.
- Store remote root, controller mirror root, and sync status.
- Stream live output through the execution-provider interface.

Acceptance checks:

- TUI/status/revive paths can read mirrored artifacts;
- incomplete runs show host id, last heartbeat, and sync status;
- heavy host diagnostics are not mirrored by default.

### Stage 4: Apollo Loopback

Introduce Apollo transport against localhost or a local subprocess service.

- Use the real Apollo request/response shape if available.
- Start the runner through Apollo while targeting localhost.
- Exercise capability preflight, status, kill, heartbeat, log streaming, and artifact mirroring.
- Keep local and Apollo-loopback providers running side by side.

Acceptance check: a loopback Apollo launch produces the same completed artifact shape as the local provider plus host
handle metadata.

### Stage 5: Single Remote Host

First true remote execution.

- Use one configured, self-credentialed remote host.
- Start with GitHub projects.
- Clone or fetch from GitHub on the remote host.
- Mirror small artifacts and stream logs back.
- Keep "one controller owns claims" as an explicit constraint.

Acceptance checks:

- a clean remote host can materialize `github:owner/repo`;
- no duplicate ProjectSpec is created for the same repo;
- remote status, heartbeat, and kill work;
- local-only `cd` and unpublished bare-git projects fail before launch with a clear reason.

### Stage 6: Host Pool And Coordinator

Only after single-host remote runs are useful.

- Add scheduling policy: explicit host, project pinning, least-loaded, or round-robin.
- Adopt the multi-machine sync coordinator idea for agent-name leases, workspace claims, heartbeat, and fencing.
- Add stale-lease recovery and abandoned workspace cleanup.
- Decide whether Apollo itself owns coordination or delegates to a separate SASE coordinator.

This stage is required before multiple controllers or a worker pool can safely launch against the same project.

## Risks And Open Questions

- Apollo API shape is unknown. SASE needs host selection, command start, status, kill, heartbeat, log streaming,
  artifact transfer, and capability preflight. If Apollo only supplies raw command execution, SASE must own leases and
  mirroring.
- Credential policy is the biggest operational risk. Self-credentialed hosts are acceptable for early stages but not
  enough for ephemeral cloud workers.
- The execution boundary touches Rust-backed launch code. Shared launch handles and lease semantics should land in
  `sase-core` once stable.
- Local file locks and PIDs do not become distributed by syncing files. Stage 6 needs a real coordinator with fencing.
- The artifact scanner assumes local files. Mirroring metadata keeps it working early; a host-aware scanner is a larger
  later change.
- Sibling repos are path-based today. Remote execution needs identity-based sibling materialization or explicit
  local-only failure.
- Completed historical artifacts can probably remain historical during identity migration, but active and resumable
  runs need stricter handling.

## Recommendation

Build Apollo support in this order:

1. Finish provider-normalized project identity for GitHub and make aliases the ergonomic front door.
2. Add host-qualified launch/process handles on the current local path.
3. Simulate remote hosts locally with separate workspace roots and artifact mirrors.
4. Add Apollo loopback.
5. Add one self-credentialed remote host, starting with GitHub projects.
6. Add host pools only after a coordinator exists.

The core invariant is simple: SASE project identity is `what repository/project is this`, while workspace paths are
`where this host materialized it`. Apollo should operate on the second concept without creating new identities for the
first.
