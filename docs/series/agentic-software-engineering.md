# Agentic Software Engineering Series

SASE uses **agentic software engineering** to mean software work where AI agents operate inside durable engineering
systems: plans, work queues, review records, tests, commits, dependencies, and handoffs. The series explains why that
coordination layer matters and how SASE implements it.

The canonical posts live on the [SASE Blog](../blog/index.md). This page is the series hub for readers who want the
launch arc in order.

## Series Track

| Order | Post                                                                                          | Status      |
| ----- | --------------------------------------------------------------------------------------------- | ----------- |
| 1     | [Why Coding Agents Need Orchestration](../blog/posts/why-coding-agents-need-orchestration.md) | Launch stub |
| 2     | ChangeSpecs: Turning Agent Output Into Reviewable Work                                        | Planned     |
| 3     | Beads: Dependency-Aware Work Units For Multi-Agent Execution                                  | Planned     |
| 4     | XPrompts: Reusable Workflows Above One-Off Prompts                                            | Planned     |
| 5     | ACE And AXE: Operating Agents From A Durable Control Plane                                    | Planned     |

## Reader Paths

Start with the [launch essay](../blog/posts/why-coding-agents-need-orchestration.md) for the motivation, then move to
the product surfaces that make the ideas concrete:

- [ACE TUI](../ace.md) for the interactive control surface.
- [Spec-Driven Development](../sdd.md) for plans, epics, and executable phase work.
- [Beads](../beads.md) for issue-like work items and dependency ordering.
- [XPrompts](../xprompt.md) for reusable prompt and workflow packaging.
- [GitHub](https://github.com/sase-org/sase) for source, issues, and implementation details.

## Publishing Notes

The blog is the canonical publishing surface for SASE essays. Series posts should keep stable slugs, include frontmatter
dates and categories, and link back here so readers can continue through the launch track without relying on archive
pages alone.
