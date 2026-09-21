# Wave 5 — Release-scoped queries and policy-driven graph analysis

> Milestone: M3 · Requirements: CORE-22..CORE-31; DATA-15..DATA-18, DATA-46..DATA-50 ·
> Depends on: W4

## Purpose

Make a published release answerable. Two complementary read surfaces are built on the same selected
manifest: DataFusion for relational joins, coverage matrices and release comparisons, and a private
NetworkX projection for reachability, cycles and explainable dependency paths. Both are
reconstructed from one manifest, so they cannot disagree about what the model is.

Impact analysis is the reason the graph exists, and the reason it must be policy-driven: following
ownership, documentation and grouping edges indiscriminately produces misleading impact reports.

## Contract references

- [data.md § DataFusion](../contracts/data.md) — DATA-15, DATA-17, DATA-18, DATA-46..DATA-50.
- [data.md § NetworkX bridge](../contracts/data.md) — DATA-16.
- [core.md § NetworkX analysis](../contracts/core.md) — CORE-22..CORE-31, the `GraphPolicy` and
  `GraphPathResult` shapes.
- Records `ARCH-TOOL-DATA-001` §4 and §11D–11E, `ARCH-TOOL-CORE-001` §8.

## Decisions taken during execution

**The graph is built from the query session, not beside it.** `build_graph` takes a
`ReleaseContext` and projects its nodes and edges out of the same DataFusion session the recipes
run in, so the hard gate — DataFusion and NetworkX read the same release — is a property of there
being one session rather than an assertion about two code paths that agree today. It also delivers
CORE-23's "minimal traversal attributes only" as the projection list rather than as a convention:
the graph cannot carry a field the `SELECT` did not ask for. The projection goes through the
expression API rather than SQL, because a side-qualified table name would otherwise have to be
interpolated into a query string — which `ruff`'s `S608` flagged, correctly, and which `data.md`
already answers with "DataFrame/expression APIs for programmatic construction".

**Three library capabilities removed code that would otherwise have been ours.** `SQLOptions` with
DDL, DML and statements disallowed makes every mutating form fail at *planning* time, so DATA-18 is
a configuration rather than a statement allow-list we would have to keep correct against every SQL
form DataFusion 54 accepts — and the same call carries the bound `param_values`, so there is no
unguarded path to the engine. `Catalog.register_schema` plus a qualified registration name gives
literally `base.elements` and `candidate.elements`, so DATA-47 needed **no change to the storage
layer**: `register_pins` has reached them with its `prefix=` since W3, and a schema nobody created
cannot be registered into, so a misspelled side fails loudly instead of landing in `public`.
`information_schema` makes the registered inventory the engine's answer rather than ours, which is
what makes DATA-46 checkable at all.

**`target_partitions` is pinned to one.** Without it a physical plan carries the host's CPU count,
and DATA-49's evidence would differ between two machines running the same release. These tables are
small enough that the parallelism is not worth the nondeterminism.

**Recursive CTEs work, and are dangerous exactly where expected.** A bounded `WITH RECURSIVE` over
a cyclic `contains` edge set terminates and returns the truncated walk; the same query without the
depth guard had not terminated after fifteen seconds. So `max_depth` is a **required** parameter
rather than a defaulted one, and `tests/unit/test_recipe_contracts.py` enforces that for every
future recursive recipe rather than for this one. The unbounded half is stated rather than run: a
suite must not contain a query that may never return.

**Plan evidence is properties, not snapshots.** A byte comparison against committed plans would
turn every DataFusion upgrade into a failed string equality that says nothing about whether the new
plan is better. What is asserted is that a plan scans only its recipe's declared tables, that a
comparison scans a base *and* a candidate table, that no host-specific repartitioning appears, and
that a relational recipe reads only the columns it needs. That immediately earned its keep:
projection pushdown does not reach inside a recursive CTE in DataFusion 54, so the containment
recipe scans `relationships` whole. Harmless at this scale, pinned with the assertion inverted so
it fails when upstream improves.

**One module imports NetworkX, and the stronger reason is typing.** The boundary mirrors
`storage/delta.py` — an ast-grep rule plus a layering test, because `ast-grep test` cannot exercise
an `ignores` glob. But `types-networkx` is the real motive: it is version-matched and imprecise
about the one thing CORE-23 makes load-bearing, because `MultiDiGraph` carries no key type
parameter and every declaration involving an edge key chose `int`. Three narrow suppressions answer
that once instead of at every call site, taking the `src` total from one to four, and each is
qualified twice — the runtime truth and the stub's own declared text — so a corrected stub fails
and the workaround is removed deliberately.

**Three NetworkX results lose canonical identity, and the signatures say so.** `simple_cycles`
returns node lists with no keys, `transitive_reduction` returns a `DiGraph` and drops them, and
`transitive_closure` mints derived edges with the integer key `0` — in the same key space as a
relationship ID. So a cycle is expanded back to *every* realization rather than one, a reduction
edge carries the set of relationships that back it, and a closure edge is returned in a record with
no relationship field at all. CORE-31's "never replace canonical relationships" is enforced by the
absence of the field rather than by a warning in a docstring.

**W1's `TraversalBehavior` is what checks a policy.** It was declared "consumed at W5" and left
unused. A policy that follows a type the profile marks not traversable, or walks a `forward_only`
type backwards, is refused at construction. The baseline marks `contains` and `justifies`
forward-only, and `justifies` is exactly the documentation edge this wave's purpose warns about.

**Direction is two values rather than three.** A traversal that changed direction mid-path would
return paths describing nothing: "A depends on B, and C also depends on B, therefore C is affected
by A" is not a dependency. A question that needs both directions is two traversals.

**No new diagnostic codes.** Graph findings are typed result DTOs, not model diagnostics.
`CORE.CONTAINMENT.CYCLE` already names the fact that a containment cycle exists, and a truncated
traversal is a property of the *query* — carried on the result as `truncated` and `limit_reached` —
rather than a statement about the model. Failures of usage raise from `queries/errors.py`, the way
`storage/errors.py` already does.

**The DATA-17 certainty guard reads the source.** A string literal following an enum member is not
retained at run time, so the test parses `results.py` with `ast` to scan each classification's name,
value and documentation. It caught its own first draft: the docstring *denying* a prediction
contained the words the scan forbids.

**Two guards are two-tier.** DATA-50 is an ast-grep rule forbidding `register_udf` and its family
under `queries/`, *and* a test that asks a real release context which functions it holds and
compares that against a bare `SessionContext` — so a UDF registered by any path fails, not only one
the rule can see. The baseline is not empty, and the test asserts that too, because a guard
comparing two empty sets would pass whatever was registered.

## Work items

1. **Release-scoped session** (DATA-46). One fresh DataFusion `SessionContext` per selected
   `ArchitectureRelease`, registering only the manifest-pinned table versions through the W3
   SnapshotProviders. It must never combine independently resolved latest versions.
2. **Explicit comparison namespaces** (DATA-47). Cross-release comparison registers named sides —
   `base.elements`, `candidate.elements` and so on. No implicit version resolution on either side.
3. **Versioned query recipes** (DATA-48). A recipe carries `query_recipe_id` and version, purpose,
   input table roles, parameter schema, expected output schema, required release context, the SQL
   or expression definition, traversal semantics and qualification cases. Initial set from data.md
   §4A: requirements with no verification method; interfaces with a missing request schema;
   application ownership across two releases; a capability-by-application coverage matrix.
4. **Bound parameters** (DATA-18). Runtime scalars go through `param_values` or the expression API,
   never string interpolation. `tests/qualification/test_data_stack.py` already asserts the
   injection case; keep and extend that pattern.
5. **Plan evidence** (DATA-49). For representative recipes capture logical, optimized and physical
   plans, EXPLAIN output where useful, DataFusion version, provider type, release IDs, recipe
   version, output schema and a deterministic fixture digest. **Plans are engine diagnostics** and
   are excluded from semantic hashes.
6. **Built-ins first** (DATA-50). No UDF, UDAF, UDWF or UDTF without a demonstrated architecture
   query gap. Recursive CTEs selectively, for naturally relational hierarchy and containment
   questions, with the behavior qualified against the pinned runtime.
7. **Read-only surface** (DATA-18). DataFusion is the query surface, not the mutation API. Edits go
   through W1 change commands and W4 publication.
8. **Graph construction** (CORE-22, CORE-23, DATA-16). Build a `MultiDiGraph` from release-selected
   records: node key is the canonical object ID, edge key is the canonical relationship ID. Minimal
   attributes only — object kind, relationship type, selected traversal context. Rich records stay
   in the tables. The graph is disposable and reproducible; no second persistent store and no
   serialized graph files.
9. **ArchitectureGraph facade** (CORE-24, CORE-25). The raw NetworkX object is private. The facade
   exposes graph and release identity, named policy selection, query methods and result DTOs, with
   no general mutation API. `nx.freeze()` is applied where useful but is only a partial guard,
   because attribute dictionaries stay mutable — the facade and minimal attributes are the real
   protection.
10. **GraphPolicy** (CORE-26, CORE-27). Versioned: policy ID and version, allowed relationship
    types, direction, allowed and excluded node kinds, context filters, max depth, max paths, max
    results, stop kinds, cycle handling. Apply through `subgraph_view()` or equivalent read-only
    filtered views rather than copying the graph.
11. **Explainable results** (CORE-28, DATA-17). `GraphPathResult` retains release ID, policy ID and
    version, start and end, ordered node IDs, **ordered relationship IDs**, relationship types,
    depth and classification. No impact result may discard the path that justifies it, and
    "potentially affected through these dependencies" must stay distinguishable from a claim that a
    change will certainly cause a failure.
12. **Bounded enumeration** (CORE-29). Policy caps are enforced before materializing results. Use
    edge-path APIs where parallel relationships matter — the existing qualification test proves two
    distinct a-to-b edges do not collapse, and that must survive into path results.
13. **Structural algorithms** (CORE-30, CORE-31). Ancestors and descendants, topological
    generations, cycle detection, strongly connected components, condensation, transitive closure
    and reduction. DAG algorithms only after DAG validation; every result maps back to canonical
    node and relationship IDs. Transitive reduction and closure are derived view data and never
    replace canonical relationships. No centrality or community scoring as a baseline notion of
    architectural importance.
14. **Named traversal recipes** (DATA-17). `trace_requirement_implementation`,
    `find_interface_dependents`, `find_containment_cycles`, `compare_architecture_releases`,
    `find_unverified_dependencies` — each declaring allowed types, direction, filters and stopping
    conditions.

## Hard gate

> DataFusion and NetworkX read the same release.
> — [agent handoff](../agent-handoff.md), M3 hard gates

Also required: cross-release comparisons use explicit sides; parallel relationship IDs remain
distinct; reachability is never reported as certain failure.

## Policy only

CORE-25 (freeze is a partial guard, asserted by test) and DATA-50 (built-ins first, enforced by a
guard test that no UDF is registered without a recorded gap).

## Executable checks

```sh
uv run pytest -m "unit or property or integration"
uv run pyrefly check
```

## Evidence

Requirement markers throughout. Plan evidence from DATA-49 is stored as a qualification artifact,
explicitly outside semantic identity.

## Risks and open questions

- **Recursive CTE support** in the pinned DataFusion 54 must be qualified, not assumed. If a
  hierarchy query needs it and it is unavailable, use NetworkX rather than forcing recursive SQL.
- **Policy vocabulary** — which relationship types belong in an impact traversal — is project
  policy and depends on W1's relationship registry. Ship a small, explicit default set.
- **Graph build cost** per query is acceptable at this scale. Caching per release is an
  optimization, not a baseline; caching across releases would break the disposability contract.
