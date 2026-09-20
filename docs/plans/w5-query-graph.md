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
