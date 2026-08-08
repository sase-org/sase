"""Cross-surface gate conformance matrix.

One fixture set, run through every surface that can answer a gate: the
headless CLI (``sase gate answer``), ACE's tracked submission path, and the
mobile host bridge. ``sase-telegram`` runs the same case ids against its own
adapter in that repo.

**This matrix exists because the surfaces drifted.** Before this epic, ACE
never copied the reviewer's note into command input, mobile copied it only
when the literal option id ``feedback`` was selected, and Telegram copied it
only when a schema listed ``feedback`` as required -- so the same gate
answered differently depending on where you tapped it. Every rule that
decides what a command receives now lives in the shared executor, and this
matrix is the thing that proves it stayed there. Assert cross-surface
agreement here, not by inspection.

Each surface declares the submission capabilities it has today
(:mod:`tests.gate_conformance._surfaces`). A case that needs a capability a
surface lacks is skipped with a message stating why that surface cannot
submit it, so coverage widens by flipping one capability flag rather than by
rewriting cases. A skip reason is a standing limitation, not a to-do: it says
what the surface cannot do and what a reviewer must do instead, never that
some pending work will fix it -- an excuse pointing at a bead outlives the
bead and silently stops collecting the coverage it deferred.
"""
