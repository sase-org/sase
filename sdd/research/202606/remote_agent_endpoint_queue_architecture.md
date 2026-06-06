---
create_time: 2026-06-06
updated_time: 2026-06-06
status: research
---

# Remote Agent Endpoint Queue Architecture

## Question

How should SASE support running agents on remote machines using an always-online
server as the endpoint that controllers and workers can send work to and pull work
from?

This note builds on the June Apollo topology research in
`sdd/research/202606/apollo_remote_agents_workspace_topology.md`. That memo
settles the main topology point: a remote machine is an execution host with its
own filesystem, credentials, process namespace, and workspace roots. This note
focuses on the remote endpoint itself: the queue, worker protocol, leases,
artifacts, and recommended implementation path.

## Summary

The best fit is a SASE-specific, pull-based remote control plane:

- an always-online SASE server keeps durable run state, leases, host inventory,
  cancellation requests, event logs, and artifact indexes;
- each remote machine runs a `sase remote worker` process that makes outbound
  HTTPS/WebSocket or long-poll requests to the server, claims compatible work,
  executes the whole SASE agent runner locally, and streams events, logs, and
  artifact manifests back;
- source code moves through real VCS remotes, not through the SASE server;
- execution hosts are self-credentialed early on: installed SASE, plugins,
  agent CLIs, `git`/`gh`, and LLM/VCS auth already exist on the worker;
- the server is a coordinator and artifact relay, not a generic shell server.

The recommended concrete backend is:

- transport: HTTPS behind Tailscale Serve for private use;
- server store: Postgres tables for runs, leases, events, workers, and artifact
  manifests;
- wakeups: long polling or WebSocket/SSE, optionally backed by Postgres
  `LISTEN`/`NOTIFY`;
- artifacts: server filesystem or object storage for larger blobs, with small
  status files mirrored eagerly.

For a zero-ops prototype, SQLite behind a single server process is acceptable,
but the durable design should target Postgres because lease/fencing correctness
is the hard part, not queue throughput.

## Current SASE Constraints

SASE is intentionally local today.

- `docs/architecture.md` says the launch flow resolves local workspace refs,
  allocates or prepares a target workspace, invokes a local LLM provider or
  workflow executor, writes local chat/artifact metadata, and exposes status
  through local state.
- `src/sase/agent/launch_types.py` returns `AgentLaunchResult(pid=...)`; the
  process handle is a local PID.
- `src/sase/running_field/_model.py` stores `RUNNING` claims as
  `#N | PID | WORKFLOW | CL_NAME | TIMESTAMP`; this is not host-qualified.
- `src/sase/core/agent_launch_wire.py` carries `project_file`, `workspace_dir`,
  `workspace_num`, and `pid` in local terms.
- `src/sase/axe/run_agent_runner.py` receives a local path, changes directory
  into it, invokes local providers, and writes local artifacts.
- `docs/mobile_gateway.md` already gives SASE a good remote API precedent: the
  Rust gateway exposes product-shaped operations and fixed JSON bridge commands,
  not arbitrary shell, cwd, environment, or file-path control from clients.
- `sdd/research/202605/multi_machine_sync.md` found that file sync does not make
  local locks or workspace claims distributed. Cross-machine work needs a real
  coordinator with leases and fencing.
- `sdd/research/202606/apollo_remote_agents_workspace_topology.md` recommends
  host-qualified process handles, stable project identity, remote materialization
  plans, self-credentialed hosts, artifact mirroring, and staged loopback before
  true remote execution.

Implication: the first remote design should launch the whole SASE runner on the
worker machine. It should not try to remote-execute each nested `git`, `gh`,
`codex`, `claude`, or workflow subprocess from a controller-side runner.

## External Prior Art

Self-hosted CI runners are the closest operational pattern.

- Buildkite's agent polls for work, runs jobs, reports status/output, and
  uploads artifacts. That is almost the SASE remote worker shape.
  Source: <https://buildkite.com/docs/agent>
- GitHub self-hosted runners connect outbound to receive job assignments and
  require outbound HTTPS, which is the right NAT/firewall stance for personal
  machines and laptops.
  Source: <https://docs.github.com/en/actions/reference/runners/self-hosted-runners>
- Temporal task queues are polled by workers, keep tasks durable when workers
  go down, and do not require workers to advertise themselves through DNS.
  Source: <https://docs.temporal.io/task-queue>
- Nomad splits server and client agents. Clients heartbeat, advertise
  capabilities, and run tasks assigned by servers.
  Source: <https://developer.hashicorp.com/nomad/docs/deploy/nomad-agent>

Queue and transport options:

- Postgres `FOR UPDATE SKIP LOCKED` is explicitly useful for multiple consumers
  accessing a queue-like table, and lets the service atomically claim rows.
  Source: <https://www.postgresql.org/docs/current/sql-select.html>
- Postgres `NOTIFY` is useful as a lightweight wakeup signal, but structured
  data should live in tables and payloads are bounded. Do not treat it as the
  durable queue.
  Source: <https://www.postgresql.org/docs/current/sql-notify.html>
- NATS JetStream is strong for durable streams, pull consumers, explicit acks,
  and horizontal workers. It is attractive if SASE later wants a broker-first
  architecture, but SASE still needs queryable run, lease, and artifact state.
  Source: <https://docs.nats.io/nats-concepts/jetstream>
- Celery and RQ show the Python task-queue path, but they are function/job
  frameworks around Redis/RabbitMQ semantics. They do not remove the need for a
  SASE-specific run protocol, artifact model, and host-qualified handles.
  Sources: <https://docs.celeryq.dev/en/main/getting-started/introduction.html>
  and <https://python-rq.org/docs/workers/>

Private access options:

- Tailscale Serve routes tailnet traffic to a local service and remains private
  when configured as Serve rather than Funnel. This matches the existing mobile
  runbook guidance.
  Source: <https://tailscale.com/docs/features/tailscale-serve>
- Cloudflare Tunnel is useful when the endpoint must be reachable from outside
  a tailnet without opening inbound firewall ports, but it creates a broader
  public-internet edge unless paired with Access/service-token policy.
  Source: <https://developers.cloudflare.com/tunnel/>

## Requirements

The endpoint must support these operations:

| Surface | Requirement |
| --- | --- |
| Submission | A controller submits a prompt/workflow against a canonical project identity and optional host labels. |
| Routing | Workers advertise host id, SASE version, installed providers, agent runtimes, OS/arch, workspace root, and concurrency. |
| Claiming | Workers claim one run at a time with a lease epoch/fencing token and heartbeat deadline. |
| Execution | The claimed unit is the whole SASE runner process on the worker, not arbitrary remote shell fragments. |
| Cancellation | Controller can request cancel; worker translates that into local process termination and reports final state. |
| Status | Server stores ordered events for queued, leased, starting, running, artifact, completed, failed, killed, stale, and sync states. |
| Logs | Live output streams to the server; bounded recent output is visible without fetching the whole remote log tree. |
| Artifacts | Small status files and manifests mirror eagerly; large blobs are uploaded explicitly or fetched on demand. |
| Workspaces | Worker materializes host-local checkouts from a provider-neutral materialization plan. |
| Secrets | Server does not copy GitHub, SSH, LLM, or agent CLI credentials to workers. Hosts are self-credentialed first. |
| Recovery | Stale leases can be marked, retried, or abandoned without trusting a synced PID file. |
| Audit | Every submit, claim, heartbeat, cancel, artifact upload, and terminal outcome is attributable to a controller or worker. |

## Alternatives

### 1. SSH from controller to remote workers

This is the fastest proof of concept: the controller SSHes into a host, runs a
command, tails logs, and copies artifacts back.

It is the wrong long-term shape. It requires controller reachability to the
worker, makes NAT/mobile hosts painful, couples launch lifetime to the
controller, pushes credential management into the controller, and does not match
the user's desired "send and pull work" endpoint.

Use SSH only as a debugging transport inside a worker implementation, not as
the product architecture.

### 2. Syncthing or Git inbox directory

A server-side `incoming/` directory plus Syncthing/Git/rclone could distribute
prompt files. Workers could watch for files and write `done.json` files back.

This gets an MVP moving but fails on the hard part: leases, cancellation,
host-capability routing, stale-worker recovery, artifact indexing, and duplicate
claim prevention. The multi-machine sync research already concluded that file
sync does not make locks distributed.

Use file sync for artifact mirroring or project-local SDD state, not as the
remote execution coordinator.

### 3. Reuse GitHub Actions, Buildkite, or another CI runner

CI runner products already solve polling workers, job assignment, logs, and
artifacts. They are valuable prior art, but they are a poor default runtime for
SASE agents:

- prompts and agent outputs are sensitive and would live in a CI system;
- interactive HITL, retry, `%wait`, ChangeSpecs, and ACE-visible agent state do
  not map cleanly to CI job states;
- SASE needs project/workspace identity independent of a repository workflow;
- users would have to operate or pay for a CI service to run personal agents.

This remains useful for isolated batch jobs, not as the main SASE remote
backend.

### 4. Temporal or Nomad

Temporal has excellent durable execution semantics, worker polling, retries,
queries, and signals. Nomad has mature host scheduling and task lifecycle
management. Either could work.

The tradeoff is operational and conceptual weight. SASE already has workflows,
agents, artifacts, ChangeSpecs, and a TUI. Adding a general orchestrator would
force SASE to map its domain into another domain while still implementing
SASE-specific artifacts, workspace materialization, prompts, and host identity.

Consider Temporal later if remote SASE grows into multi-step durable workflows
across many hosts. For the first personal endpoint, a narrower SASE control
plane is easier to reason about.

### 5. NATS JetStream

JetStream is the strongest broker-only option. Pull consumers, explicit acks,
redelivery, key-value CAS, and object store all line up with remote workers.

The catch is that SASE needs more than a broker: a queryable run table, lease
epochs, host inventory, artifact manifests, audit logs, and ACE/mobile APIs.
Using JetStream alone would still require a service and a database-like view.

Use JetStream if the SASE remote endpoint later needs high fan-out, disconnected
edge-to-cloud messaging, or broker-level replication. It is not the simplest
first endpoint.

### 6. Custom SASE control plane with durable DB

This is the recommended option. The server owns SASE-specific state and exposes
a narrow worker/controller API. Workers pull work over outbound connections and
run SASE locally.

Postgres is boring in the right way here:

- one transactional source of truth for run rows, leases, events, and artifact
  manifests;
- `SKIP LOCKED` can claim queued rows without lock contention;
- `LISTEN`/`NOTIFY` can wake long-polling workers after inserts;
- SQL queries can power ACE/mobile status without building read models first;
- backups and migrations are understandable on an always-online home server.

SQLite is fine for loopback and a single-process MVP if the API owns all writes,
but do not expose SQLite files to workers or synced folders.

## Recommended Architecture

### Components

```text
Controller / ACE / mobile
  |
  | HTTPS inside tailnet
  v
SASE remote server
  - run queue
  - leases and fencing
  - worker inventory
  - event log
  - artifact manifests/blobs
  - controller and worker auth
  |
  | long poll / WebSocket / SSE
  v
sase remote worker on each execution host
  - self-credentialed
  - host-local workspace store
  - local SASE runner subprocesses
  - log and artifact streamer
```

The always-online server can also run a worker, but that should be explicit:
server role and worker role are separate.

### Data Model

Minimum server tables:

```text
workers(
  host_id,
  display_name,
  machine_id,
  version,
  labels_json,
  capabilities_json,
  max_concurrency,
  last_heartbeat_at,
  state
)

runs(
  run_id,
  canonical_project_id,
  prompt_snapshot,
  materialization_plan_json,
  workflow_name,
  desired_labels_json,
  status,
  priority,
  created_at,
  updated_at,
  assigned_host_id,
  lease_epoch,
  lease_expires_at,
  cancel_requested_at,
  terminal_outcome_json
)

run_events(
  event_id,
  run_id,
  seq,
  host_id,
  lease_epoch,
  kind,
  payload_json,
  created_at
)

artifacts(
  artifact_id,
  run_id,
  host_id,
  kind,
  name,
  size_bytes,
  content_hash,
  storage_uri,
  mirrored,
  created_at
)
```

Key invariants:

- `run_id` is globally unique and appears in server state, worker logs, mirrored
  artifacts, and local `agent_meta.json`.
- A worker event is accepted only if `(run_id, host_id, lease_epoch)` matches
  the current lease.
- A stale lease does not imply the process is dead; it means the server no
  longer trusts that worker to mutate the run without revalidation.
- Retries are explicit. Do not blindly retry a run that may have modified a
  workspace unless the runner reported a safe pre-execution failure.

### Worker Protocol

Controller-facing operations:

- `POST /v1/runs`: submit a prompt/workflow/materialization plan.
- `GET /v1/runs/{run_id}`: inspect status.
- `GET /v1/runs/{run_id}/events`: read ordered events.
- `POST /v1/runs/{run_id}/cancel`: request cancellation.
- `GET /v1/artifacts/{artifact_id}`: fetch mirrored artifact.

Worker-facing operations:

- `POST /v1/workers/register`: register host identity and capabilities.
- `POST /v1/workers/{host_id}/heartbeat`: renew worker liveness.
- `POST /v1/work/claim`: long-poll for compatible work and receive a lease.
- `POST /v1/runs/{run_id}/heartbeat`: renew the run lease.
- `POST /v1/runs/{run_id}/events`: append structured run events.
- `POST /v1/runs/{run_id}/logs`: append bounded log chunks.
- `POST /v1/runs/{run_id}/artifacts`: upload manifests or blobs.
- `POST /v1/runs/{run_id}/complete`: terminal success/failure/killed state.

Use WebSocket later if the log stream needs lower latency. Long polling is
simpler and matches self-hosted runner prior art.

### Execution Unit

The worker should execute a SASE-owned command, not arbitrary shell:

```text
sase remote worker-run --run-id <run_id> --lease-epoch <epoch> --input <json>
```

That command can internally call the same local runner code used by ordinary
SASE launches, but with remote metadata injected:

- `SASE_REMOTE_RUN_ID`
- `SASE_REMOTE_HOST_ID`
- `SASE_REMOTE_LEASE_EPOCH`
- `SASE_REMOTE_SERVER_URL`
- host-local `SASE_HOME`
- host-local workspace root

The runner still invokes local LLM and VCS providers. That keeps the uniform
agent runtime contract intact and avoids runtime-specific remote branches.

### Workspace And Source Materialization

A remote run should carry a provider-neutral materialization plan:

```text
canonical_project_id
project_display_name
workflow_type
vcs_family
vcs_provider_name
remote_identity
clone_url_or_fetch_url
checkout_target
provider_extra
```

GitHub projects are the best first target because `owner/repo` can be cloned or
fetched on the worker. Local `#cd` and unpublished bare-git projects should fail
before remote launch unless there is an explicit path mapping, shared mount, or
published remote.

### Artifact Strategy

Mirror these eagerly:

- `agent_meta.json`
- `running.json`
- `done.json`
- `workflow_state.json`
- prompt snapshots
- plan/question/HITL markers
- response transcript summary
- bounded recent log chunks
- explicit user artifacts selected by the runner

Keep these host-local or fetch-on-demand:

- huge provider debug logs;
- full `axe/logs` trees;
- large generated images/PDFs unless explicitly attached;
- raw workspace clones.

The ACE Agents tab can read the server mirror first, then offer fetch actions for
remote-only blobs.

### Security

Default deployment should be private:

- bind the server on loopback or tailnet-only;
- expose it through Tailscale Serve for personal use;
- avoid Tailscale Funnel for default remote agents;
- use Cloudflare Tunnel only when non-tailnet access is required, and then put
  Access or service tokens in front of it;
- issue per-machine worker tokens with rotation and revocation;
- never accept arbitrary shell/cwd/env/argv from controllers;
- do not forward GitHub, SSH, LLM, or Codex/Claude credentials through the
  server by default;
- audit all submit, claim, cancel, heartbeat, and artifact events.

The server will see prompt text unless a later encryption layer is added. Treat
the endpoint as sensitive SASE infrastructure.

## Integration Plan

### Phase 0: Host-Qualified Local Handles

No remote execution yet.

- Add `host_id`, `run_id`, `execution_provider`, `lease_epoch`, and
  `process_id` fields to launch and artifact metadata.
- Keep local PID behavior but stop treating PID alone as an agent identity.
- Update scanning/status code to display `pid@host` where available.

This matches the Apollo Stage 1 recommendation and makes local behavior
remote-ready.

### Phase 1: Loopback Server And Worker

- Add a `sase remote server` command.
- Add a `sase remote worker --server ...` command.
- Use loopback on the same machine.
- Submit a remote run through a CLI command.
- Execute the whole runner through the worker.
- Mirror minimal artifacts back to the server.

Acceptance check: loopback remote launch produces the same visible outcome as a
local launch plus host-qualified metadata.

### Phase 2: One Remote Host, GitHub Only

- Run the server on the always-online machine.
- Expose it privately with Tailscale Serve.
- Run one self-credentialed worker on a second machine.
- Support GitHub materialization plans only.
- Stream output and upload small artifacts.
- Support cancel and stale-heartbeat detection.

Acceptance check: `#gh:owner/repo` can run on the worker, appears in local
status/ACE, and can be killed from the controller.

### Phase 3: ACE And Mobile Integration

- Add remote host selection to launch surfaces.
- Add a remote runs panel or merge remote runs into the Agents tab with clear
  `host_id`.
- Let mobile submit remote-safe prompt launches through product-shaped routes.
- Add artifact fetch actions.

### Phase 4: Multi-Worker Scheduling

- Add host labels, project pinning, capacity, priority, and least-loaded
  scheduling.
- Add stale lease recovery policy and explicit retry classes.
- Add server-side retention and artifact pruning.

### Phase 5: Stronger State Sync

- Promote ChangeSpec and SDD state sync according to the multi-machine sync
  research.
- Decide whether server-owned state events should become the source of truth for
  remote runs instead of mirrored host-local SASE files.

## Open Questions

- Should the server live in `../sase-core` next to `sase_gateway`, or start as a
  Python service for faster iteration? The route discipline and wire contracts
  argue for Rust eventually; the existing launch side effects argue for a Python
  worker first.
- How much of `~/.sase/projects/<project>/` must be available on a worker before
  launch? The smallest viable version can send a serialized ProjectSpec snapshot
  and materialization plan, but existing runner code expects local files.
- Should remote workers spawn detached background runners or run foreground
  child processes supervised by the worker? Supervised foreground children make
  cancellation, logs, and terminal state cleaner for the first remote version.
- How should `%wait` dependencies work across hosts? The safest first rule is
  controller/server-owned dependency resolution before queueing dependent work.
- What is the user-facing model for local-only refs such as `#cd`? The first
  version should fail clearly unless a host path mapping is configured.

## Recommendation

Implement a SASE-specific pull-based remote control plane, not SSH remoting,
not file-sync work queues, and not a full external orchestrator.

The first production-worthy shape should be:

1. Add host-qualified launch handles locally.
2. Build `sase remote server` with a Postgres-backed run queue, leases, worker
   inventory, event log, and artifact manifest store.
3. Build `sase remote worker` as a self-credentialed outbound worker that claims
   runs, executes the whole SASE runner locally, heartbeats with a lease epoch,
   streams logs, and uploads/mirrors artifacts.
4. Put the endpoint behind Tailscale Serve by default.
5. Start with GitHub projects and one remote host, then add host pools only
   after stale-lease recovery and host-qualified artifact scanning are solid.

This preserves SASE's existing local execution semantics while adding the one
thing file sync cannot provide: a durable, host-aware coordinator that knows who
owns each run right now.
