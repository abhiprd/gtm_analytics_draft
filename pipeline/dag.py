"""Task-graph primitives for the orchestration layer: the Node record, the
import-time DAG validation, topological ordering and node selection.

This module knows nothing about *which* nodes exist (see pipeline/nodes.py)
or how they execute (see pipeline/runner.py). It is deliberately small and
dependency-free (stdlib only) so the graph logic can be lifted into Airflow,
Dagster or Prefect unchanged: a Node is a name, a command, and the names of
the nodes it needs first.

Grain: one Node per independently runnable unit of work (a generator batch,
a test gate, a dbt invocation, one analytics artifact, one check).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple

VALID_INTERPRETERS = ("root", "semantic", "dashboard")
VALID_PROFILES = ("verify", "ci", "rebuild", "monitor")
VALID_KINDS = (
    "generator", "qa", "dbt", "analytics", "governance", "semantic",
    "dashboard", "freshness",
)


class DagError(ValueError):
    """Raised for any structural defect in the graph or in a selection."""


@dataclass(frozen=True)
class Node:
    """One unit of work.

    argv            Command tokens. The token "{python}" is replaced with the
                    interpreter named by `interpreter`; a token of the form
                    "{glob:PATTERN}" expands to the sorted, repo-relative
                    matches of PATTERN (so a node can name a test file group
                    without a shell).
    deps            Names of nodes that must have finished first.
    interpreter     Which Python runs the node: the root interpreter that
                    started the pipeline, or a dedicated virtualenv
                    (semantic/.venv, dashboard/.venv). A node whose
                    interpreter is absent is reported as skipped, never as
                    passed.
    cwd             Working directory, repo-relative.
    profiles        Named selections this node belongs to (see VALID_PROFILES).
    opt_in          True for nodes that overwrite tracked data (the raw-data
                    generators). Opt-in nodes are never pulled in by a
                    profile or by another node's upstream closure -- only by
                    --with-generators or by naming one explicitly.
    requires        Repo-relative paths that must exist before the node
                    starts; a missing one fails the node with a message
                    naming the node that produces it, instead of a
                    traceback from deep inside the artifact.
    mutates         Repo-relative paths the node writes (documentation and
                    manifest only; never consulted for scheduling).
    as_of           Canonical as-of dates the node's entrypoint evaluates at
                    (metadata for `plan`; the contract test keeps it aligned
                    with the freshness contract).
    fail_patterns   Regexes; a line in the node's output matching one marks
                    the node failed even when the process exits 0. Analytics
                    entrypoints report a failed validation check by printing
                    "[FAIL]" rather than by exiting nonzero.
    expected_fail   Regexes for [FAIL] lines that are documented, expected
                    findings rather than defects (for example a regression
                    artifact reporting honestly that a channel's effect is
                    not significant); matching lines do not fail the node.
    skip_patterns   Regexes; a line in the output of an otherwise passing
                    (exit 0, no failed check) node matching one marks the
                    node SKIPPED with that line as the reason, for a node
                    that detects at run time that it cannot do its optional
                    work (the executive summary without an API key). It is
                    never reported as passed.
    skip_is_expected
                    True when such a skip is a normal configuration state
                    rather than a broken environment: --strict then does
                    not turn it into exit 3. It is still listed as SKIPPED
                    in the output and the manifest.
    """
    name: str
    kind: str
    description: str
    argv: Tuple[str, ...]
    deps: Tuple[str, ...] = ()
    interpreter: str = "root"
    cwd: str = "."
    profiles: FrozenSet[str] = frozenset({"verify"})
    opt_in: bool = False
    requires: Tuple[str, ...] = ()
    mutates: Tuple[str, ...] = ()
    as_of: Tuple[str, ...] = ()
    fail_patterns: Tuple[str, ...] = ()
    expected_fail: Tuple[str, ...] = ()
    skip_patterns: Tuple[str, ...] = ()
    skip_is_expected: bool = False
    timeout_s: int = 1800


def validate(nodes: Sequence[Node]) -> None:
    """Import-time invariants: unique names, known dependencies, known
    kinds/interpreters/profiles, every node in at least one profile, acyclic,
    and opt-in nodes (the generators) depending only on other opt-in nodes.
    A regular node may depend on a generator; that edge is dropped when
    generators are not selected."""
    seen: Dict[str, Node] = {}
    for n in nodes:
        if n.name in seen:
            raise DagError(f"duplicate node name: {n.name}")
        seen[n.name] = n
        if n.kind not in VALID_KINDS:
            raise DagError(f"{n.name}: unknown kind {n.kind!r}")
        if n.interpreter not in VALID_INTERPRETERS:
            raise DagError(f"{n.name}: unknown interpreter {n.interpreter!r}")
        bad = set(n.profiles) - set(VALID_PROFILES)
        if bad:
            raise DagError(f"{n.name}: unknown profile(s) {sorted(bad)}")
        if not n.profiles:
            raise DagError(f"{n.name}: belongs to no profile")
        if not n.description.strip():
            raise DagError(f"{n.name}: missing description")
        if not n.argv:
            raise DagError(f"{n.name}: empty argv")
    for n in nodes:
        for d in n.deps:
            if d not in seen:
                raise DagError(f"{n.name}: depends on unknown node {d!r}")
            if d == n.name:
                raise DagError(f"{n.name}: depends on itself")
        if n.opt_in:
            for d in n.deps:
                if not seen[d].opt_in:
                    raise DagError(f"{n.name}: opt-in node depends on non-opt-in {d}")
    topological_order(nodes)  # raises DagError on a cycle


def topological_order(nodes: Sequence[Node],
                      subset: Optional[Iterable[str]] = None) -> List[Node]:
    """Kahn's algorithm, deterministic: among nodes that are ready at the
    same time, the one declared first runs first. Edges to nodes outside
    `subset` are ignored (their work is assumed already present on disk).
    Raises DagError naming the nodes on a cycle."""
    by_name = {n.name: n for n in nodes}
    index = {n.name: i for i, n in enumerate(nodes)}
    wanted = set(by_name) if subset is None else set(subset)
    unknown = wanted - set(by_name)
    if unknown:
        raise DagError(f"unknown node(s): {sorted(unknown)}")
    indegree = {name: 0 for name in wanted}
    children: Dict[str, List[str]] = {name: [] for name in wanted}
    for name in wanted:
        for d in by_name[name].deps:
            if d in wanted:
                indegree[name] += 1
                children[d].append(name)
    ready = sorted((n for n, k in indegree.items() if k == 0), key=index.get)
    order: List[Node] = []
    while ready:
        name = ready.pop(0)
        order.append(by_name[name])
        released = []
        for c in children[name]:
            indegree[c] -= 1
            if indegree[c] == 0:
                released.append(c)
        ready = sorted(ready + released, key=index.get)
    if len(order) != len(wanted):
        stuck = sorted(n for n, k in indegree.items() if k > 0)
        raise DagError(f"dependency cycle among: {stuck}")
    return order


def upstream_closure(nodes: Sequence[Node], roots: Iterable[str],
                     include_opt_in: bool) -> FrozenSet[str]:
    """`roots` plus every node they (transitively) need. Opt-in ancestors are
    left out unless `include_opt_in` or a root is itself opt-in (naming a
    generator explicitly means its upstream generators are required)."""
    by_name = {n.name: n for n in nodes}
    roots = list(roots)
    for r in roots:
        if r not in by_name:
            raise DagError(f"unknown node: {r!r}")
    allow_opt_in = include_opt_in or any(by_name[r].opt_in for r in roots)
    out = set()
    stack = list(roots)
    while stack:
        name = stack.pop()
        if name in out:
            continue
        if by_name[name].opt_in and not allow_opt_in and name not in roots:
            continue
        out.add(name)
        stack.extend(by_name[name].deps)
    return frozenset(out)


def downstream_closure(nodes: Sequence[Node], roots: Iterable[str],
                       universe: Iterable[str]) -> FrozenSet[str]:
    """`roots` plus every node in `universe` that (transitively) needs one."""
    by_name = {n.name: n for n in nodes}
    roots = list(roots)
    for r in roots:
        if r not in by_name:
            raise DagError(f"unknown node: {r!r}")
    uni = set(universe) | set(roots)
    out = set(roots)
    changed = True
    while changed:
        changed = False
        for name in uni:
            if name not in out and any(d in out for d in by_name[name].deps):
                out.add(name)
                changed = True
    return frozenset(out)


@dataclass(frozen=True)
class Selection:
    """The ordered nodes a run will execute, plus how they were chosen."""
    order: Tuple[Node, ...]
    profile: str
    with_generators: bool
    only: Tuple[str, ...] = ()
    from_: Tuple[str, ...] = ()
    with_deps: bool = True
    notes: Tuple[str, ...] = field(default_factory=tuple)


def select(nodes: Sequence[Node], profile: str = "verify",
           with_generators: bool = False, only: Sequence[str] = (),
           from_: Sequence[str] = (), with_deps: bool = True) -> Selection:
    """Resolve CLI flags to an ordered node list.

    Default: every node in `profile`, plus (with_generators) every opt-in
    node. `only` narrows to the named nodes and, unless with_deps is False,
    their required upstream. `from_` keeps the named nodes and everything
    downstream of them within the profile universe. Both can combine: the
    result is their intersection."""
    if profile not in VALID_PROFILES:
        raise DagError(f"unknown profile {profile!r}; choose from {list(VALID_PROFILES)}")
    by_name = {n.name: n for n in nodes}
    universe = {n.name for n in nodes
                if profile in n.profiles and not n.opt_in}
    if with_generators:
        universe |= {n.name for n in nodes if n.opt_in}
    notes: List[str] = []

    chosen = set(universe)
    if only:
        for o in only:
            if o not in by_name:
                raise DagError(f"unknown node: {o!r} (see `python3 -m pipeline plan --all`)")
        if with_deps:
            chosen = set(upstream_closure(nodes, only, with_generators))
        else:
            chosen = set(only)
    if from_:
        for f in from_:
            if f not in by_name:
                raise DagError(f"unknown node: {f!r} (see `python3 -m pipeline plan --all`)")
        # Downstream is computed over the profile universe, widened to
        # include opt-in descendants when an opt-in node is the root.
        uni = set(universe)
        if any(by_name[f].opt_in for f in from_):
            uni |= {n.name for n in nodes if n.opt_in}
        down = downstream_closure(nodes, from_, uni)
        chosen = (chosen & down) if only else set(down)
    if not chosen:
        raise DagError(f"profile {profile!r} selects no nodes")
    order = topological_order(nodes, chosen)
    return Selection(tuple(order), profile, with_generators, tuple(only),
                     tuple(from_), with_deps, tuple(notes))
