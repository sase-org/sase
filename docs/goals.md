# Goals

Goals are durable records of outcomes a person wants: what will be true, how you'll
know, and what happened along the way. Create one with `sase goal new`, watch it in
`sase goal list`, and cite it in any prompt as `@goal:<id>`.

A goal is not a bead and not a plan's `goal:` field:

- A **bead** tracks a unit of agent work (a bug, a phase, a CI failure). It is born
  inside the machine workflow and dies there.
- A plan's **`goal:` frontmatter field** is one line of intent at the top of a plan
  file. It points nowhere and enforces nothing.
- A **goal** (`⌖7k2mq`, `goal:7k2mq`) is a person-owned record with its own id, status,
  timeline, and sync story. Agents can read and cite goals, but only a person creates,
  reshapes, or settles one.

## Statuses

| Status    | Meaning                                              |
| --------- | ---------------------------------------------------- |
| `active`  | Open and being pursued.                              |
| `review`  | Awaiting a human decision (used by later workflows). |
| `done`    | Settled as verified or acknowledged.                 |
| `dropped` | Settled as canceled, merged, or superseded.          |

Running versus Idle is derived from agent liveness elsewhere and is never stored on the
goal. `draft` and `claimed` states belong to later epics; this ledger reserves the
vocabulary but does not produce those events.

## CLI tour

Bare `sase goal` defaults to `sase goal list`:

```text
sase goal new -t "Try goals" -o "I can see this goal from apollo"
sase goal list                        # unsettled goals, fastest path
sase goal list -s dropped             # history scan, newest first
sase goal show 7k2mq                  # the full card
sase goal edit 7k2mq -o "New outcome" # reshape
sase goal drop 7k2mq -w "tried it"    # settle as canceled
sase goal reopen 7k2mq -m "retry"     # unsettle again
sase goal merge 7k2mq -i 3fq9t -w "same work"
sase goal doctor                      # check the ledger
sase goal doctor --repair             # fix markers (human only)
```

Ids accept `7k2mq`, `⌖7k2mq`, `goal:7k2mq`, and `goal:<project>@7k2mq` forms.
`-j/--json` prints the wire structs (`GoalListWire`, `GoalStateWire`) that the gateway
and later surfaces consume. `new`, `edit`, `drop`, `reopen`, `merge`, and
`doctor --repair` are human verbs: inside an agent run they refuse with exit 2 and a
pointer to `list` and `show`. `list`, `show`, and `doctor` work everywhere.

## Citing goals

Write `@goal:7k2mq` in any prompt to expand a one-line citation (title, status, outcome,
and where to look). A citation never binds the agent to the goal — binding is a later
epic. Citing a settled goal is allowed. `goal:` is also a first-class artifact kind:
`sase artifact read goal:7k2mq` prints the full card, `show` prints metadata, `path`
prints the goal's event directory, and `open` pages the card.

## Where goals live

Shared goals live in a top-level `goals/` directory inside the project's beads sidecar
repository, written only through the host-owned hidden clone. Bead commits never sweep
`goals/`, and goal writes never touch beads. Shared goal titles, outcomes, criteria, and
timelines are exactly as public as bead titles already are, because the beads repo is
public.

Set `goals.visibility: local` to keep a project's ledger machine-local: it is never
published, and every surface says `local only`. Projects without a usable host sidecar
fall back to local-only automatically.

Publishing is synchronous and bounded (`goals.push_timeout_seconds`). A failed publish
is never a failed write: the event is durable locally, the footer shows `↑ unpublished`,
and the outbox retries on the next mutating command and on the sidecar auto-sync tick.

## Freshness

Every list header says honestly how fresh it is: `synced Ns ago`, `never synced`, or
`local only`. The watermark advances only on a successful integration. Reads spawn a
single-flight background fetch when the watermark is older than
`goals.fetch_ttl_seconds`; pass `-f/--fresh` to integrate synchronously before reading.

## Doctor

`sase goal doctor` reconciles live markers against reduced state, reports unreadable
goals (including id collisions, with the remedy), stray files, and projection status.
`--repair` only adds or removes markers and rebuilds the projection — it never touches
an event file. An event ledger from a newer sase fails closed with a `run sase update`
hint instead of guessing.

## Coming next

Later epics add deterministic agent binding, claims with verification, local drafts, the
Goals tab, and the attention cutover. The event vocabulary and status machine are
frozen, so those producers extend the ledger without breaking what exists here.
