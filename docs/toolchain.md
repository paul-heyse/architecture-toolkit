# Toolchain

Exact executable dependency state is governed by `uv.lock` and `tools.lock.json`. Contracts may
select a **target** capability before the dependency/config migration is implemented; current versus
target is explicit below.

## Python

Python 3.14.7; uv 0.12.7; one project, lock and environment.

| Library/tool | Current state | Contract role / target |
| --- | --- | --- |
| Pydantic | installed | strict domain/commands/manifests, discriminated variants, JSON Schema |
| PyArrow | installed | explicit schemas, typed batches/streams/Dataset interchange |
| deltalake | installed | Python-only versioned table persistence/history |
| DataFusion | installed | release-scoped relational queries and plan evidence |
| NetworkX | installed | disposable policy-driven MultiDiGraph analysis |
| ruamel.yaml | installed | round-trip YAML authoring and source locations |
| Jinja2 | installed | strict deterministic textual projection rendering |
| lxml | installed | secure namespace-aware XML, schema validation and C14N |
| Hypothesis | installed | property and state-machine qualification |
| pytest | installed | test orchestration and future requirement evidence |
| Ruff | installed | lint/format; target selective RUF/PT/PTH/S expansion |
| Pyrefly | installed | Pydantic/pytest-aware type checks, Protocols, strict type coverage |
| types-networkx / types-jsonschema / types-lxml / pyarrow-stubs | installed (dev) | stubs for runtime packages shipping no `py.typed`; pyarrow's are qualified against the pinned 25.x, see below |
| MkDocs | installed docs group | offline portal engine |
| Material for MkDocs | target, unpinned | portal theme after exact-version qualification |

Use `uv sync --locked --all-groups`.

### Pyrefly configuration

D-032 is implemented. `ty` and `[tool.ty.environment]` are removed; `[tool.pyrefly]` checks
`src`, `tests` and `scripts` under Python 3.14.

`required-version = ">=1.3.1,<1.4.0"` makes a mismatched checker a fatal configuration error, not
a silent behaviour change — Pyrefly does not follow semantic versioning and any release may
introduce new diagnostics. Upgrading is a deliberate engineering change: bump the pin, rerun both
platforms, and record the new coverage floor.

`[tool.pyrefly.coverage]` narrows *measurement* to `src` while the *check* surface stays wide.
Without it the strict figure is diluted by unannotated test bodies (63.83% against 85.71%).
CI enforces `--strict --fail-under 100`, the measured `src` floor. W0 set 85, W1 raised it to 98
as annotated domain and validation code landed, and W3 raised it to 100 once `pyarrow-stubs`
closed the last `[coverage-partial]` function. It never moves down without a recorded reason.

A floor at the measured figure is the point rather than an accident. At 98 a partial annotation
can be introduced and sit unnoticed until two percent of the package has accumulated them; at 100
the first one fails CI, in the change that introduced it, where it is cheapest to fix. If a wave
meets a genuinely untypable third-party surface, lowering the floor is a decision with a recorded
reason — which is exactly the conversation that should happen — not a silent slide.

No baseline file is used (CORE-60). Suppressions are narrow `# pyrefly: ignore[error-code]`
comments with a local rationale. `pyrefly infer` never runs in CI (CORE-62).

### Third-party typing gaps

`pyarrow` and `networkx` ship no `py.typed`; `ruamel.yaml` (0.19.1), `datafusion`, `deltalake`,
`pydantic` and `jinja2` do — ruamel's `compose`, `parse`, `load` and `dump` return `Any`, so the
authoring adapter declares every return type itself. Stubs cover networkx, jsonschema, lxml and,
from W3, pyarrow.

**`pyarrow-stubs` is adopted, and qualified rather than trusted.** Its declared target is pyarrow
major 20 while the lock pins 25.0.1, which is why W1 rejected it. A version mismatch makes a stub
*possibly* wrong, not *certainly* wrong, and the difference is measurable: adopting
`pyarrow-stubs==20.0.0.20260819` took strict `src` coverage from 99.62% to 100.00% and left
`pyrefly check` at zero errors, because the one remaining `[coverage-partial]` function was
`storage.datafusion_adapter.register_snapshot` and its only untyped name was `pa.Schema`.

The qualification is two files, because a stub can fail in two directions and neither test sees
the other's failure:

- `tests/static/pyarrow_surface.py` writes every pyarrow call `storage/` makes with the type it
  must have and asserts it with `assert_type`. A stub that *misreports* the 25.x surface fails
  `pyrefly check` here rather than at run time.
- `tests/qualification/test_pyarrow_stub.py` asserts the runtime truth, and separately parses the
  installed `.pyi` files to check that every class and function they declare still exists on the
  runtime module — staleness in the other direction.

Two divergences were found and both are pinned rather than papered over. `Table.equals` is
declared as returning a `Table` and returns a `bool`; `pyarrow.compute.dictionary_decode` is
absent from the stub and present in pyarrow 25.0.1. The first is the dangerous kind — a wrong
type type-checks — so `storage.interchange.tables_equal` gives callers the true one; the second
is a single narrow `# pyrefly: ignore[missing-attribute]`. Both are asserted *as declared* in the
static harness, so a stub release that corrects either one fails the build and the workaround is
removed on purpose instead of being left behind.

The fallback, if a future stub release misreports more of the surface than this, is project-owned
partial stubs under `typings/pyarrow/` on the Pyrefly `search-path`, which outranks site
packages. It is not needed today and is not carried speculatively.

### types-networkx

`types-networkx` is version-matched to the locked networkx, so unlike `pyarrow-stubs` it is not
stale. It is *imprecise*, in the one place this toolkit depends on most: `MultiDiGraph` carries no
key type parameter, so every declaration involving a multigraph edge key had to choose something
and chose `int`. CORE-23 makes ours a canonical relationship ID.

Four divergences are pinned, three of them by a suppression in `queries/_nx.py` — the only module
that imports NetworkX, kept that way by `rules/graph-networkx-only-in-adapter.yml` and a layering
test, so the `Any` boundary is answered once rather than at every call site:

| declaration | stub says | runtime does |
| --- | --- | --- |
| `subgraph_view` `filter_edge` | `Callable[[_Node, _Node, int], bool]` | the key is whatever was used — a relationship ID |
| `all_simple_edge_paths` | yields node lists or pairs | yields `(source, target, key)` triples for a multigraph |
| `Graph.add_edges_from` | `_EdgePlus` stops at three-tuples | accepts the documented `(u, v, key, data)` form |
| `transitive_closure` | returns `Graph`, whose `edges` view takes no `keys` | returns a `MultiDiGraph` |

Each is asserted twice in `tests/qualification/test_networkx_stub.py`: the runtime truth, so the
workaround is known to be necessary, and the stub's own declared text, so a corrected stub fails
and the suppression is removed on purpose. `tests/static/networkx_surface.py` pins what the adapter
returns — which matters more here than usual, because a suppression is a place the checker was told
to stop looking, so the outputs of the functions containing them are pinned where it is still
looking.

The repository holds ten narrow `# pyrefly: ignore[...]` comments in total. Four are in `src`: one
in `storage/interchange.py` and three in `queries/_nx.py`. The other six are in tests — one in
`tests/static/pyarrow_surface.py`, one in `tests/qualification/test_networkx_stub.py`, and four
where a unit test deliberately does the thing the checker forbids in order to assert that it is
forbidden at run time too. There is still no baseline file (CORE-60).

## DataFusion / Delta compatibility

The current qualified baseline materializes a specifically selected Delta version to PyArrow before
DataFusion registration. Under the current scaffold lock, direct native FFI is incompatible.
The data contract defines Dataset/stream/native provider candidates; none may replace the fallback
without exact-stack qualification.

## Vendor tools

Run `uv run python scripts/bootstrap_tools.py`. `tools.lock.json` pins URLs, versions and SHA256
checksums. Downloads stay in ignored `.tools/`; bootstrap does not start services or modify system Java.

| Tool | Current pin | Use |
| --- | --- | --- |
| Temurin JRE | 21.0.12.1+1 | local Java runtime |
| PlantUML MIT build | 1.2026.8 | ArchiMate/UML/ERD and portable SVG |
| Structurizr unified WAR | 2026.06.28 | C4 validate/export; future static rich C4 artifact |
| OMG BPMN XSD set | BPMN 2.0.2 | local XML Schema validation |
| Graphviz | host package, version recorded | current PlantUML layout |

Install Graphviz with the platform package manager. It is not currently pinned identically across
platforms; rendered SVG bytes are not semantic architecture identity.

## Target projection additions

Qualification-gated, not currently installed/pinned by this document:
- ArchiMate Exchange XSD set/local resolver;
- bpmn-moddle;
- bpmnlint correctness rules;
- bpmn-auto-layout;
- bpmn-js local viewer;
- optional bpmn-to-image;
- Material for MkDocs 9.x;
- optional local Kroki adapter only if it simplifies operations.

### Node runtime

Introducing Node for the BPMN stack is **approved**. It remains qualification-gated in the sense
that nothing is pinned yet, but it is no longer an open scope question: PROJ-29, PROJ-31 and
PROJ-32 may depend on it.

A host Node installation does not satisfy PROJ-34. The setup host has Node 24.20.0 via a
per-shell `fnm` path, which is neither reproducible, checksummed, nor present on a CI runner at a
known version. PROJ-34 requires **one pinned vendor runtime**, bootstrapped exactly like the
Temurin JRE:

- a `node` entry per supported platform in `tools.lock.json` with version, URL and SHA256;
- download, digest check and safe extraction into ignored `.tools/` by `scripts/bootstrap_tools.py`;
- a single committed dependency lock for the bpmn.io packages;
- no second application or workspace, and no persistent service by default.

Pinning lands in W7b, which is the first wave that executes the BPMN toolchain. Node 24 or later
is required only if `bpmn-to-image` is adopted; the lighter bpmn-js SVG export path has no such
floor, so pick the pinned major after the PROJ-31 and PROJ-33 qualification decisions rather than
before them.

## Security

- local/private rendering by default;
- no remote PlantUML/Structurizr includes in generated baseline;
- XML parser/resolver never fetches network schemas at validation time;
- bounded subprocesses with argument arrays and captured diagnostics;
- no public Kroki or other renderer endpoint for confidential models by default.

## Upgrade process

1. review accepted contract and affected requirements;
2. update one dependency/tool family deliberately;
3. regenerate Python lock or vendor pin/checksum;
4. run targeted interoperability tests;
5. run both-platform qualification where relevant;
6. record changed capabilities/limitations in qualification/handoff;
7. keep historical release/tool provenance intact.

Do not check downloaded binaries, extracted tools, runtime stores or caches into Git.
