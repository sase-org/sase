---
title: Structured Agentic Software Engineering
---

<div class="sase-home">

<section class="sase-hero">
  <div class="sase-hero__copy">
    <p class="sase-kicker">SASE</p>

    <h1>Structured Agentic Software Engineering</h1>

    <p class="sase-lede">
      SASE is a Python toolkit for coordinating coding-agent work: durable plans, tracked handoffs, reviewable
      changes, resumable runs, and automation that can move across model and version-control providers.
    </p>

    <div class="sase-actions">
      <a class="md-button" href="getting_started/">Getting Started</a>
      <a class="md-button" href="/downloads/sase-handbook.pdf">Download PDF</a>
      <a class="md-button" href="https://github.com/sase-org/sase">View on GitHub</a>
      <a class="md-button" href="blog/posts/structured-agentic-software-engineering/">Launch Post</a>
    </div>

  </div>

  <figure class="sase-hero__visual">
    <img src="images/sase_overview.png" alt="Overview of SASE coordinating parallel coding agents, isolated workspaces, and durable workflow state">
  </figure>
</section>

<section class="sase-section sase-section--tight">
  <p class="sase-section__eyebrow">Why SASE exists</p>

  <h2>One prompt is not an engineering system</h2>

  <p>
    A single coding-agent run can produce a patch. Real projects also need a place to store intent, pass work between
    agents, order dependencies, track review state, retry failed runs, run background automation, and record what
    happened. SASE provides that coordination layer without tying the workflow to one model provider or one terminal app.
  </p>
</section>

<section class="sase-section">
  <p class="sase-section__eyebrow">Start by role</p>

  <h2>Pick the surface that matches your work</h2>

  <div class="sase-card-grid sase-card-grid--four">
  <article class="sase-card">
  <h3>I am setting up a repo</h3>

  <p>
    Run explicit initialization subcommands to write agent memory, refresh generated SDD guide files, and inspect,
    preview, or deploy optional provider skill files before handing work to agents.
  </p>

<a href="init/">Open initialization</a>

  </article>

  <article class="sase-card">
  <h3>I want a TUI for agent work</h3>

  <p>
    Use ACE, the Agentic ChangeSpec Explorer TUI, to navigate ChangeSpecs, live agents, notifications, and automation
    state from one terminal interface.
  </p>

<a href="ace/">Open the ACE guide</a>

  </article>

  <article class="sase-card">
  <h3>I want durable work units</h3>

  <p>
    Use ChangeSpecs for PR-sized review state and Beads for plan, epic, and phase dependencies that can drive
    multi-agent execution.
  </p>

<a href="sdd/">Learn the SDD flow</a>

  </article>

  <article class="sase-card">
  <h3>I need shared agent memory</h3>

  <p>
    Use instruction memory loaded through AGENTS.md, audited long-term reads, and reviewed proposals for
    agent-suggested updates.
  </p>

<a href="memory/">Open memory</a>

  </article>

  <article class="sase-card">
  <h3>I want reusable agent workflows</h3>

  <p>
    Use XPrompts for reusable prompt templates and workflow specs for repeatable multi-step automation.
  </p>

<a href="xprompt/">Build with XPrompts</a>

  </article>

  <article class="sase-card">
  <h3>I want implementation context</h3>

  <p>
    Use the architecture overview, command index, and development guide to understand the CLI surface, source layout,
    provider boundaries, and docs workflow.
  </p>

<a href="architecture/">Read the architecture map</a>

  </article>

  <article class="sase-card">
  <h3>I want editor completions</h3>

  <p>
    Use the xprompt LSP and editor helper bridge for prompt completion, snippets, hover, diagnostics, and
    jump-to-definition.
  </p>

<a href="editor/">Open editor integration</a>

  </article>
  </div>
</section>

<section class="sase-section sase-split">
  <div>
  <p class="sase-section__eyebrow">Core primitives</p>

  <h2>The coordination model</h2>

  <p>
    SASE keeps the work state outside the chat transcript. Plans, ChangeSpecs, beads, agent artifacts, and workflow
    records let agents be scheduled, resumed, reviewed, retried, or handed off without relying on one session's context
    window.
  </p>
  </div>

  <div class="sase-primitive-list">
  <ul>
    <li><strong>ProjectSpecs and ChangeSpecs</strong> track project lifecycle, PR-sized work, commits, review state, comments, mentors, and lifecycle transitions.</li>
    <li><strong>Beads</strong> provide git-native issue tracking for plans, executable epics, phase dependencies, and agent handoff.</li>
    <li><strong>XPrompts</strong> turn prompt templates into reusable workflows with reference expansion and typed inputs.</li>
    <li><strong>ACE</strong> is the interactive control surface for daily work.</li>
    <li><strong>Axe Automation</strong> runs background hooks, mentors, maintenance jobs, and scheduled workflows.</li>
    <li><strong>Provider and workspace abstractions</strong> route agent launches, VCS operations, and workspace setup through plugin-backed boundaries.</li>
  </ul>
  </div>
</section>

<section class="sase-section">
  <p class="sase-section__eyebrow">How the pieces connect</p>

  <h2>Designed around real agent handoffs</h2>

  <div class="sase-image-grid">
  <figure>
    <img src="images/sase-component-communication.png" alt="SASE component communication diagram">
    <figcaption>Component boundaries keep TUI, daemon, workflow, and provider concerns explicit.</figcaption>
  </figure>
  </div>
</section>

<section class="sase-section">
  <p class="sase-section__eyebrow">Next clicks</p>

  <h2>Move from overview to practice</h2>

  <div class="sase-card-grid sase-card-grid--four">
  <article class="sase-card sase-card--compact">
  <h3>Find a command</h3>

  <p>Use the CLI index to route from a command to its detailed owner page.</p>

<a href="cli/">Open the CLI reference</a>

  </article>

  <article class="sase-card sase-card--compact">
  <h3>Understand the system</h3>

  <p>See how CLI, ACE, axe, workflows, providers, and the Rust core fit together.</p>

<a href="architecture/">Open architecture</a>

  </article>

  <article class="sase-card sase-card--compact">
  <h3>Contribute locally</h3>

  <p>Review setup, verification commands, source layout, and docs deployment.</p>

<a href="development/">Open development</a>

  </article>

  <article class="sase-card sase-card--compact">
  <h3>Read the launch essay</h3>

  <p>Why coding agents need orchestration above individual provider CLIs.</p>

<a href="blog/posts/structured-agentic-software-engineering/">Read the essay</a>

  </article>

  <article class="sase-card sase-card--compact">
  <h3>Start with ACE</h3>

  <p>Learn the terminal interface for day-to-day SASE work.</p>

<a href="ace/">Open ACE</a>

  </article>

  <article class="sase-card sase-card--compact">
  <h3>Open the blog</h3>

  <p>Read launch posts and longer essays as they publish.</p>

<a href="blog/">Open the blog</a>

  </article>

  <article class="sase-card sase-card--compact">
  <h3>Download the handbook</h3>

  <p>Keep the current public docs and launch articles in one static PDF.</p>

<a href="/downloads/sase-handbook.pdf">Download PDF</a>

  </article>

  <article class="sase-card sase-card--compact">
  <h3>View the code</h3>

  <p>Inspect the implementation, issues, and project direction.</p>

<a href="https://github.com/sase-org/sase">Open GitHub</a>

  </article>
  </div>
</section>

</div>
