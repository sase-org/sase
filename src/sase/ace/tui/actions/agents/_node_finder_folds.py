"""Fold-state helpers for the Node Finder snapshot.

Split from :mod:`_node_finder_snapshot`: facet-driven unmet-ancestor
walks and the keep-all fast path for the fold filter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

    AgentIdentity = tuple[AgentType, str, str | None]


def unmet_with_facets(
    complete: list[Agent],
    fold_manager: Any,
    parents: dict[str, Agent],
    parent_keys: dict[int, str | None],
    hidden_steps: set[int],
    identity_of: dict[int, AgentIdentity] | None = None,
) -> dict[AgentIdentity, tuple[str, ...]]:
    """Return each row's unmet ancestor fold keys, nearest first.

    Facet-driven equivalent of :func:`unmet_ancestor_folds` for one
    snapshot: parent keys and hidden-step flags come from the single
    per-open facet read instead of re-deriving plan-chain predicates once
    per row. Cycle, bound, and missing-parent guards match the reveal
    preflight exactly, so rows with invalid ancestry are omitted the same
    way; any agent missing from the tables falls back to a direct read.

    Ancestor chains are deterministic (each agent resolves to one parent),
    so one agent's requirement list is its own edge plus its parent's
    already-resolved list. Shared clan/session ancestors resolve once per
    snapshot instead of once per member; per-pair fold-level checks memoize
    the same way. Results match the historical per-row walk exactly.
    """
    from ...models._agent_tree import agent_parent_fold_key
    from ...models.fold_state import FoldLevel
    from ..navigation._agent_reveal import fold_requirement_is_met

    bound = len(complete) + 1
    get_level = fold_manager.get
    # ``met`` memoizes the fold-level check per distinct ``(fold_key,
    # level)`` pair.
    met: dict[tuple[str, FoldLevel], bool] = {}

    def _met(fold_key: str, level: FoldLevel) -> bool:
        try:
            return met[(fold_key, level)]
        except KeyError:
            result = fold_requirement_is_met(get_level(fold_key), level)
            met[(fold_key, level)] = result
            return result

    if not hidden_steps:
        # Without hidden steps every requirement in the roster carries
        # ``EXPANDED`` (``FULLY_EXPANDED`` only guards hidden non-clan
        # rows), so chains resolve per distinct parent fold key instead
        # of per agent: members under one clan container share one walk.
        # Cycle, bound, and missing-parent guards match the per-agent
        # walk exactly, so rows with invalid ancestry are omitted the
        # same way; ``_met`` still consults live fold levels per key.
        key_memo: dict[str, tuple[tuple[tuple[str, FoldLevel], ...], bool]] = {}

        def _resolve_key(
            start_key: str,
        ) -> tuple[tuple[tuple[str, FoldLevel], ...], bool]:
            """Resolve one parent key's chain iteratively.

            Returns ``(requirements, valid)`` where requirements lists
            ``(fold_key, EXPANDED)`` nearest-first for a hypothetical row
            whose own edge is ``start_key``. Shared ancestors resolve
            once per snapshot; a cycle, a missing owner, or a chain at
            the bound marks every key on the walk invalid, mirroring
            the per-agent stack guards (including the memoized-ancestor
            rewrite on bound overflow).
            """
            hit = key_memo.get(start_key)
            if hit is not None:
                return hit
            walk_keys: list[str] = []
            walk_set: set[str] = {start_key}
            current_key = start_key
            while True:
                owner = parents.get(current_key)
                if owner is None:
                    for stale_key in walk_keys:
                        key_memo[stale_key] = ((), False)
                    key_memo[start_key] = ((), False)
                    return (), False
                owner_id = id(owner)
                if owner_id in parent_keys:
                    owner_key = parent_keys[owner_id]
                else:
                    owner_key = agent_parent_fold_key(owner)
                # The current key's own edge is part of every chain
                # through it, so it joins the walk before any break.
                walk_keys.append(current_key)
                if owner_key is None:
                    base_reqs: tuple[tuple[str, FoldLevel], ...] = ()
                    base_valid = True
                    base_key: str | None = None
                    break
                base_hit = key_memo.get(owner_key)
                if base_hit is not None:
                    base_reqs, base_valid = base_hit
                    base_key = owner_key
                    break
                if owner_key in walk_set:
                    for stale_key in walk_keys:
                        key_memo[stale_key] = ((), False)
                    key_memo[start_key] = ((), False)
                    return (), False
                walk_set.add(owner_key)
                current_key = owner_key
            if not base_valid:
                for stale_key in walk_keys:
                    key_memo[stale_key] = ((), False)
                assert base_key is not None
                key_memo[base_key] = (base_reqs, False)
                return (), False
            requirements = base_reqs
            for key in reversed(walk_keys):
                if len(requirements) + 1 >= bound:
                    for stale_key in walk_keys:
                        key_memo[stale_key] = ((), False)
                    if base_key is not None:
                        key_memo[base_key] = (base_reqs, False)
                    return (), False
                requirements = ((key, FoldLevel.EXPANDED),) + requirements
                key_memo[key] = (requirements, True)
            # Every break above appended the start key to the walk, so
            # the unwind always spliced (and memoized) it.
            return key_memo[start_key]

        # Both the chain and the unmet set depend only on the parent
        # key, so each distinct key pays one walk and one ``_met`` scan
        # no matter how many members share it. Identity comes from the
        # facet table (the same value the property would build).
        miss_memo: dict[str, tuple[str, ...]] = {}
        keyed_unmet: dict[AgentIdentity, tuple[str, ...]] = {}
        for agent in complete:
            agent_id = id(agent)
            try:
                agent_key = parent_keys[agent_id]
            except KeyError:
                agent_key = agent_parent_fold_key(agent)
            if agent_key is None:
                continue
            resolved = key_memo.get(agent_key)
            if resolved is None:
                resolved = _resolve_key(agent_key)
            requirements, valid = resolved
            if not valid:
                continue
            try:
                missing = miss_memo[agent_key]
            except KeyError:
                missing = miss_memo[agent_key] = tuple(
                    fold_key
                    for fold_key, level in requirements
                    if not _met(fold_key, level)
                )
            if missing:
                if identity_of is not None:
                    try:
                        identity = identity_of[agent_id]
                    except KeyError:
                        identity = agent.identity
                else:
                    identity = agent.identity
                keyed_unmet[identity] = missing
        return keyed_unmet

    # ``memo`` maps ``id(agent)`` to ``(requirements, valid)`` where
    # requirements lists ``(fold_key, level)`` nearest-first exactly as the
    # historical walk.
    memo: dict[int, tuple[tuple[tuple[str, FoldLevel], ...], bool]] = {}

    def _edge(
        agent: Agent, agent_id: int
    ) -> tuple[str | None, FoldLevel, Agent | None]:
        if agent_id in parent_keys:
            parent_key = parent_keys[agent_id]
        else:
            parent_key = agent_parent_fold_key(agent)
        if parent_key is None:
            return None, FoldLevel.EXPANDED, None
        parent = parents.get(parent_key)
        if parent is None:
            return parent_key, FoldLevel.EXPANDED, None
        if agent_id in hidden_steps:
            is_hidden = True
        elif agent_id in parent_keys:
            # Roster members use the table: ``hidden_steps`` holds
            # exactly the hidden ones.
            is_hidden = False
        else:
            is_hidden = agent.is_hidden_step
        return (
            parent_key,
            (
                FoldLevel.FULLY_EXPANDED
                if is_hidden and not parent_key.startswith("clan:")
                else FoldLevel.EXPANDED
            ),
            parent,
        )

    def _resolve(
        agent: Agent,
    ) -> tuple[tuple[tuple[str, FoldLevel], ...], bool]:
        """Resolve one agent's chain iteratively with cycle detection.

        The explicit stack mirrors the historical ``visited`` walk: an edge
        back into the current stack marks the whole stack invalid, a
        missing parent marks it invalid, and a memoized ancestor splices
        its already-resolved requirements in. Bound accounting matches the
        historical ``range(bound)`` loop: a chain terminates validly only
        when its total edge count stays under ``bound``.
        """
        agent_id = id(agent)
        hit = memo.get(agent_id)
        if hit is not None:
            return hit
        # The common shape is a single edge onto an already-resolved
        # parent (one clan/session container above many members): splice
        # the parent's requirements directly instead of allocating the
        # walk stack. The checks mirror the general loop's first
        # iteration exactly — root and missing-parent edges resolve the
        # same way, a memoized invalid parent propagates invalid, and a
        # chain that would overflow the bound falls through to the exact
        # general path (including its ancestor-poisoning branch).
        parent_key, level, parent = _edge(agent, agent_id)
        if parent is None:
            if parent_key is None:
                result: tuple[tuple[tuple[str, FoldLevel], ...], bool] = ((), True)
            else:
                result = ((), False)
            memo[agent_id] = result
            return result
        # ``_edge`` returns a non-``None`` parent only with a non-``None``
        # key, so the chain below splices ``str`` keys.
        assert parent_key is not None
        parent_hit = memo.get(id(parent))
        if parent_hit is not None and parent_hit[1] and len(parent_hit[0]) + 1 < bound:
            requirements = ((parent_key, level),) + parent_hit[0]
            memo[agent_id] = (requirements, True)
            return requirements, True
        stack: list[tuple[Agent, int, str, FoldLevel, Agent]] = []
        stack_ids: set[int] = set()
        current = agent
        while True:
            current_id = id(current)
            hit = memo.get(current_id)
            if hit is not None:
                parent_reqs, parent_valid = hit
                break
            if current_id in stack_ids:
                for _, stale_id, _, _, _ in stack:
                    memo[stale_id] = ((), False)
                return (), False
            parent_key, level, parent = _edge(current, current_id)
            if parent is None:
                if parent_key is None:
                    parent_reqs, parent_valid = (), True
                else:
                    for _, stale_id, _, _, _ in stack:
                        memo[stale_id] = ((), False)
                    memo[current_id] = ((), False)
                    return (), False
                break
            assert parent_key is not None
            stack.append((current, current_id, parent_key, level, parent))
            stack_ids.add(current_id)
            current = parent
        if not parent_valid:
            for _, stale_id, _, _, _ in stack:
                memo[stale_id] = ((), False)
            memo[id(current)] = (parent_reqs, False)
            return (), False
        # Splice the stack back out: each frame's requirements are its own
        # edge plus everything beneath it, exactly as a standalone walk
        # from that frame would collect.
        suffix: tuple[tuple[str, FoldLevel], ...] = parent_reqs
        for _, frame_id, frame_key, frame_level, _ in reversed(stack):
            if len(suffix) + 1 >= bound:
                for _, stale_id, _, _, _ in stack:
                    memo[stale_id] = ((), False)
                memo[id(current)] = (parent_reqs, False)
                return (), False
            suffix = ((frame_key, frame_level),) + suffix
            memo[frame_id] = (suffix, True)
        memo[id(current)] = (parent_reqs, True)
        req_list = list(suffix)
        return tuple(req_list), True

    unmet: dict[AgentIdentity, tuple[str, ...]] = {}
    for agent in complete:
        requirements, valid = _resolve(agent)
        if not valid:
            continue
        missing = tuple(
            fold_key for fold_key, level in requirements if not _met(fold_key, level)
        )
        if missing:
            unmet[agent.identity] = missing
    return unmet


def expanded_roster_keep_all(
    complete: list[Agent],
    projection: Any,
    parent_keys: dict[int, str | None],
    fold_keys: dict[int, str | None],
    hidden_steps: set[int],
    is_monitor_map: dict[int, bool],
    is_gate_map: dict[int, bool],
    is_child_row_map: dict[int, bool],
) -> list[Agent] | None:
    """Return ``list(complete)`` when the fold filter would keep every row.

    Snapshot-local fast path for :func:`filter_agents_by_fold_state`, whose
    fold counts this caller discards. With no hidden step, no monitor/gate
    turn, every parent key owned, and no collapsed level on any owner's
    chain, every row is visible: hidden-only parents need a hidden child,
    turn gating needs a turn, and the remaining visibility rule is one
    non-collapsed owner chain per row. Owner chains resolve over distinct
    fold keys with memoization; a cycle falls back to the exact filter.
    ``None`` means the fast path does not apply. The facet tables cover
    every roster id by construction, except the turn/child maps, which
    only hold non-plain rows and fall back to the same live read for a
    missing id (a plain row is never a turn or a child row).
    """
    from ...models.fold_state import FoldLevel

    if hidden_steps:
        return None
    if any(is_monitor_map.values()) or any(is_gate_map.values()):
        return None
    # Owner index built exactly like the filter's: a non-child row wins a
    # repeated key, uniquely-keyed child rows still register, and legacy
    # children repeating their parent's key never own it.
    owners_by_key: dict[str, Agent] = {}
    owners_child_row: dict[str, bool] = {}
    for agent in complete:
        agent_id = id(agent)
        key = fold_keys[agent_id]
        if key is None:
            continue
        # The child-row maps only hold non-plain rows (plain values are
        # bools, never ``None``), so a missing id falls back to the same
        # live read every consumer uses. ``dict.get`` beats
        # try/except here: misses are the common case, and raising per
        # plain row costs more than the lookup.
        agent_is_child = is_child_row_map.get(agent_id)
        if agent_is_child is None:
            agent_is_child = agent.is_child_row
        existing = owners_by_key.get(key)
        # ``owners_child_row`` is populated exactly when ``owners_by_key``
        # is, so an existing owner always has a stored child flag: the
        # original ``dict.get`` default only ever wasted a property call.
        if existing is not None and (not owners_child_row[key] or agent_is_child):
            continue
        if agent_is_child and parent_keys[agent_id] == key:
            continue
        owners_by_key[key] = agent
        owners_child_row[key] = agent_is_child
    get_level = projection.get
    visible: dict[str, bool] = {}
    visiting: set[str] = set()

    def _owner_chain_visible(key: str) -> bool | None:
        hit = visible.get(key)
        if hit is not None:
            return hit
        if key in visiting:
            return None
        owner = owners_by_key.get(key)
        if owner is None:
            visible[key] = False
            return False
        if get_level(key) is FoldLevel.COLLAPSED:
            visible[key] = False
            return False
        visiting.add(key)
        owner_parent_key = parent_keys.get(id(owner))
        if owner_parent_key is None:
            result = True
        else:
            sub = _owner_chain_visible(owner_parent_key)
            if sub is None:
                return None
            result = sub
        visiting.discard(key)
        visible[key] = result
        return result

    # Distinct keys only: shared clan/session ancestors resolve once.
    # First-occurrence order is preserved, so the early exit behaves
    # exactly as the full scan — without materializing a roster-sized
    # dedup dict per open.
    seen_parents: set[str] = set()
    for parent_key in parent_keys.values():
        if parent_key is None or parent_key in seen_parents:
            continue
        seen_parents.add(parent_key)
        if _owner_chain_visible(parent_key) is not True:
            return None
    return list(complete)


__all__ = [
    "expanded_roster_keep_all",
    "unmet_with_facets",
]
