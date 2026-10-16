---
title: Structured Agentic Software Engineering
description:
  Run, review, and land work from parallel coding agents in one terminal workspace.
hide:
  - navigation
  - toc
---

<div class="sase-home">

<section class="sase-hero">
  <div class="sase-hero__copy">
    <p class="sase-kicker">SASE</p>

    <h1>Run a team of coding agents. Keep every change reviewable.</h1>

    <p class="sase-lede">
      SASE runs Claude Code, Codex, and other agent CLIs in parallel,
      isolated workspaces, and lets you track, review, and land their work from one
      terminal UI.
    </p>

    <p class="sase-pill">Alpha &middot; Linux &amp; macOS &middot; needs one authenticated agent CLI</p>

<!-- BEGIN GENERATED: install-command -->
<p class="sase-install-command">Install with <code>uv tool install "sase>=0.18"</code></p>
<!-- END GENERATED: install-command -->

```bash
uv tool install "sase>=0.18"
sase doctor
sase tui
```

    <div class="sase-actions">
      <a class="md-button md-button--primary" href="start/first-run/">Run your first agent (15 min)</a>
      <a class="md-button" href="concepts/">How SASE works</a>
    </div>

  </div>

  <figure class="sase-hero__visual">
    <video controls preload="none" poster="images/blog/sase_ace_multi_model_fanout_still.png" aria-label="One GitHub prompt fans out to three live Claude, Codex, and Antigravity agents in isolated workspaces, supervised from sase's TUI">
      <source src="videos/sase_ace_multi_model_fanout.mp4" type="video/mp4" />
      One prompt fans out to parallel agents in isolated workspaces, supervised from
      sase's TUI.
    </video>
    <figcaption>One prompt, three live agents, three models — supervised from one terminal UI.</figcaption>
  </figure>
</section>

<section class="sase-section">
  <p class="sase-section__eyebrow">What SASE gives you</p>

  <h2>One place to run agents and land their work</h2>

  <div class="sase-card-grid sase-card-grid--four">
  <article class="sase-card">
  <h3>Parallel, isolated runs</h3>

  <p>
    Each agent works in its own workspace, so parallel runs never clash.
  </p>

<a href="concepts/agents/">How agents run</a>

  </article>

  <article class="sase-card">
  <h3>Supervise from one TUI</h3>

  <p>
    Follow prompts, status, diffs, and results from one terminal interface.
  </p>

<a href="concepts/">How SASE works</a>

  </article>

  <article class="sase-card">
  <h3>Durable, reviewable work</h3>

  <p>
    Outcomes, plans, and changes stay recorded and reviewable across runs.
  </p>

<a href="concepts/work-units/">How work is tracked</a>

  </article>

  <article class="sase-card">
  <h3>Reusable prompts and automation</h3>

  <p>
    Turn repeated instructions into macros and let scheduled work run itself.
  </p>

<a href="concepts/prompts/">How prompts grow</a>

  </article>
  </div>
</section>

<section class="sase-section">
  <p class="sase-section__eyebrow">How these docs are organized</p>

  <h2>Pick the door that matches your goal</h2>

  <div class="sase-card-grid sase-card-grid--four">
  <article class="sase-card">
  <h3>Learn</h3>

  <p>Walk the path from install to first landed change.</p>

<a href="start/">Get started</a>

  </article>

  <article class="sase-card">
  <h3>Do</h3>

  <p>Solve one goal at a time, from setup to recovery.</p>

<a href="guides/">Guides</a>

  </article>

  <article class="sase-card">
  <h3>Understand</h3>

  <p>Learn the ideas behind agents, work units, and landing.</p>

<a href="concepts/">Concepts</a>

  </article>

  <article class="sase-card">
  <h3>Look up</h3>

  <p>Find a flag, key, keybinding, or term when you need it.</p>

<a href="reference/">Reference</a>

  </article>
  </div>
</section>

<section class="sase-section sase-footer-row">
  <p>
    <a href="blog/posts/structured-agentic-software-engineering/">Launch essay</a>
    &middot;
    <a href="blog/">Blog</a>
    &middot;
    <a href="/downloads/sase-handbook.pdf">Handbook (PDF)</a>
    &middot;
    <a href="contribute/acknowledgements/">Acknowledgements</a>
  </p>
</section>

</div>
