---
title: Structured Agentic Software Engineering
---

<div class="sase-home">

<section class="sase-hero">
  <div class="sase-hero__copy">
    <p class="sase-kicker">SASE</p>

    <h1>Structured Agentic Software Engineering</h1>

    <p class="sase-lede">
      SASE is a Python toolkit for software engineering workflows around coding agents: durable planning, tracked
      handoffs, reviewable changes, resumable runs, and provider-portable automation.
    </p>

    <div class="sase-actions">
      <a class="md-button md-button--primary" href="blog/why-coding-agents-need-orchestration/">Read the launch essay</a>
      <a class="md-button" href="ace/">Start with ACE</a>
      <a class="md-button" href="series/agentic-software-engineering/">Explore the series</a>
      <a class="md-button" href="https://github.com/sase-org/sase">View on GitHub</a>
    </div>

  </div>

  <figure class="sase-hero__visual">
    <img src="images/sase_overview.jpg" alt="Overview of SASE coordinating agents, prompts, workflows, and engineering state">
  </figure>
</section>

<section class="sase-section sase-section--tight">
  <p class="sase-section__eyebrow">Why SASE exists</p>

  <h2>One prompt is not an engineering system</h2>

  <p>
    A single coding-agent run can produce a patch. Real projects also need intent capture, handoff, dependency ordering,
    review state, retries, background automation, and a record of what happened. SASE provides that coordination layer
    without tying the workflow to one model provider or one terminal app.
  </p>
</section>

<section class="sase-section">
  <p class="sase-section__eyebrow">Start by role</p>

  <h2>Pick the surface that matches your work</h2>

  <div class="sase-card-grid sase-card-grid--three">
  <article class="sase-card">
  <h3>I want a TUI for agent work</h3>

  <p>Use ACE to navigate ChangeSpecs, live agents, notifications, and automation state from one terminal interface.</p>

<a href="ace/">Open the ACE guide</a>

  </article>

  <article class="sase-card">
  <h3>I want durable work units</h3>

  <p>Use ChangeSpecs and Beads to track planned work, dependencies, commits, review state, and multi-agent phase execution.</p>

<a href="sdd/">Learn the SDD flow</a>

  </article>

  <article class="sase-card">
  <h3>I want reusable agent workflows</h3>

  <p>Use XPrompts and workflow specs to package prompts, scripts, provider routing, and repeatable automation.</p>

<a href="xprompt/">Build with XPrompts</a>

  </article>
  </div>
</section>

<section class="sase-section sase-split">
  <div>
  <p class="sase-section__eyebrow">Core primitives</p>

  <h2>The coordination model</h2>

  <p>
    SASE keeps the work state outside the chat transcript. Agents can be scheduled, resumed, reviewed, retried, or handed
    off because the project has durable primitives for intent, execution, and automation.
  </p>
  </div>

  <div class="sase-primitive-list">
  <ul>
    <li><strong>ChangeSpecs</strong> track CL/PR-sized work, commits, review state, comments, mentors, and lifecycle transitions.</li>
    <li><strong>Beads</strong> provide git-native issue tracking for plans, executable epics, phase dependencies, and agent handoff.</li>
    <li><strong>XPrompts</strong> turn prompt templates into reusable workflows with reference expansion and typed inputs.</li>
    <li><strong>ACE</strong> is the interactive control surface for daily work.</li>
    <li><strong>AXE</strong> runs background hooks, mentors, maintenance jobs, and scheduled workflows.</li>
    <li><strong>Provider and workspace abstractions</strong> keep the orchestration layer portable across coding agents and VCS providers.</li>
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

  <figure>
    <img src="images/sase_tui_tabs_infographic.png" alt="SASE ACE TUI tab overview">
    <figcaption>ACE gives operators one place to inspect agents, changes, notifications, and automation state.</figcaption>
  </figure>
  </div>
</section>

<section class="sase-section">
  <p class="sase-section__eyebrow">Next clicks</p>

  <h2>Move from overview to practice</h2>

  <div class="sase-card-grid sase-card-grid--four">
  <article class="sase-card sase-card--compact">
  <h3>Read the launch essay</h3>

  <p>Why coding agents need orchestration above individual provider CLIs.</p>

<a href="blog/why-coding-agents-need-orchestration/">Read the essay</a>

  </article>

  <article class="sase-card sase-card--compact">
  <h3>Start with ACE</h3>

  <p>Learn the terminal interface for day-to-day SASE work.</p>

<a href="ace/">Open ACE</a>

  </article>

  <article class="sase-card sase-card--compact">
  <h3>Explore the series</h3>

  <p>Follow the agentic software engineering launch track as it grows.</p>

<a href="series/agentic-software-engineering/">Explore the series</a>

  </article>

  <article class="sase-card sase-card--compact">
  <h3>View the code</h3>

  <p>Inspect the implementation, issues, and project direction.</p>

<a href="https://github.com/sase-org/sase">Open GitHub</a>

  </article>
  </div>
</section>

</div>
