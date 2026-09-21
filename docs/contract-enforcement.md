# Contract enforcement

How the rules in [the contracts](implementation-contract.md) are made executable, and why the
mechanism is layered rather than uniform.

## Three tiers

Pick the highest tier that applies. Each is harder to get wrong than the one below it.

| Tier | Mechanism | Use for |
| --- | --- | --- |
| 1. Parser | `tomllib`, `json`, a JSON Schema validator | Structured data: `uv.lock`, `reference/*.json`, `schemas/*.json` |
| 2. Syntax tree | `ast-grep scan` against `rules/` | Python source: imports, banned APIs, call shapes, security flags |
| 3. Text | Line scanning over `git ls-files` | Prose, generated assets, anything with no grammar |

Tier three is last because it is the tier that rots. A regex nothing exercises is
indistinguishable from a regex that matches nothing — which is exactly what happened to the
`contract` pattern in `schemas/requirements.schema.json`, which carried a double-escaped
`\\.md` for the life of the file and matched none of the three values it guarded. No check
noticed, because nothing validated the index against its own schema.

Two rules follow from that:

- **Do not hand-write a regex where a parser exists.** `uv.lock` is TOML; parse it. A requirement
  index has a schema; validate against it. A path names a file; resolve it.
- **Every guard asserts a known-bad input is caught**, not only that the current tree is clean.
  `scripts/check_schema.py` and `scripts/check_boundaries.py` each carry a self-test, and every
  ast-grep rule has valid and invalid cases under `rule-tests/`.

## Tier 2: ast-grep

`sgconfig.yml` points at `rules/` and `rule-tests/`. Rules match the parsed tree, so:

- a banned construct inside a comment or string literal is not a false positive;
- the same construct split across lines is not a false negative;
- a regex, where still needed, is scoped to a named metavariable rather than a whole line.

The load-bearing example is `no-implicit-latest-delta-version`, which enforces global invariant 5
("Published releases never resolve an implicit latest table version"):

```yaml
rule:
  pattern: DeltaTable($$$ARGS)
  not:
    has:
      stopBy: end
      pattern:
        context: f(version=$V)
        selector: keyword_argument
```

This accepts a `version=` argument wherever it appears in the call, including several lines below
the opening parenthesis, and rejects the call when it is absent. No line-oriented expression
gets both of those right.

`context`/`selector` is needed because `version=$V` alone parses as an assignment statement, not a
keyword argument. When a pattern will not match, `ast-grep run -p '<pattern>' -l python
--debug-query=ast` shows how it was parsed.

### Rule tests

```sh
ast-grep scan    # apply rules to the tree
ast-grep test    # apply rule-tests/ to the rules
```

`ast-grep test` reports `N` for a valid case that matched (the rule is too broad) and `M` for an
invalid case that did not (too narrow). Both happened while writing the current rules: an
unanchored constraint matched `import networkx_stub`, and `import x as y` bound the metavariable
to the whole aliased node rather than the module name. Both were caught by the rule's own tests
before the rule was committed, which is the entire argument for this layer.

Snapshots live in `rule-tests/__snapshots__/`. Regenerate deliberately with
`ast-grep test --update-all` and review the diff; a changed snapshot means a rule's
behaviour changed.

### Current rules

| Rule | Enforces |
| --- | --- |
| `no-implicit-latest-delta-version` | invariant 5; DATA-21, DATA-51 |
| `domain-layer-imports` | Package boundaries; DATA-01 |
| `storage-no-graph-import` | DATA-01, CORE-22 |
| `queries-no-direct-delta` | DATA-34, DATA-51 |
| `no-validation-bypass` | CORE-09, CORE-10 — scope widened in W1 to `tests/` and `scripts/` |
| `no-shell-invocation` | projections.md rendering security |
| `secure-xml-parser` | CORE-40, CORE-41 |
| `ruamel-only-in-authoring` | CORE-17 — `ruamel` imports are confined to `domain/authoring/`; the exclusion glob is proven by `tests/unit/test_layering.py` |
| `releases-no-direct-delta` | DATA-20, DATA-51 — the release layer reaches Delta only through `storage/delta.py`, so the application protocol and the storage engine stay in different places |
| `graph-networkx-only-in-adapter` | CORE-22, CORE-24, DATA-16 — NetworkX is confined to `queries/_nx.py`, which is where the narrow `types-networkx` suppressions live; the exclusion glob is proven by `tests/unit/test_layering.py` |
| `changes-not-imported-by-lower-layers` | DATA-26 — nothing below the change layer imports it, so the import direction that made `changes/` its own package cannot silently regress; the exclusion glob is proven by `tests/unit/test_layering.py` |
| `change-classification-has-no-default` | DATA-26 — the classification table is subscripted, never read with a default, so its totality test keeps having consequences |
| `queries-builtins-first` | DATA-50 — no UDF, UDAF, UDWF or UDTF without a recorded capability gap; paired with a runtime check that a release context registers nothing beyond DataFusion's own functions |

Each wave adds the rules for the boundaries it introduces; see `docs/plans/`.

## Policy requirements and their guards

Some requirements are satisfied by a documented constraint rather than a feature. They are the
ones most likely to be quietly skipped, so each is paired with an executable guard.

| Requirement | Constraint | Guard |
| --- | --- | --- |
| DATA-01 | Pydantic, Arrow, DataFusion, NetworkX and deltalake hold distinct responsibilities over one logical model | `domain-layer-imports`, `storage-no-graph-import`, `queries-no-direct-delta` |
| DATA-02 | SQLite, and immutable Parquet plus manifests, remain credible alternatives. The stack is justified by typed interchange, coherent versioned snapshots and queryability — **not** by data volume. Substituting either is an architecture decision, not a refactor. | deny-list in `check_boundaries.py` keeps a competing engine out of the lock |
| DATA-32 | Each library keeps a bounded role; the standard library covers ordinary utilities | per-package import rules above, plus the lock deny-list |
| DATA-33 | No overlapping dataframe, database, orchestration or ORM layer | `check_boundaries.py` reads the resolved `uv.lock`, not `pyproject.toml`, so a transitive pull is caught |
| DATA-35 | One Python project, one lock, one environment; application code is Python-only | tracked-payload check rejects a committed `.venv/`; the lock is the single resolution source |
| DATA-36 | Notion owns narrative, Git owns executable contracts, Delta stays host-local, Dropbox gets dated exports | private-marker scan over `git ls-files`; tracked-payload check rejects `.runtime/`, `.tools/`, `.context/` |
| CORE-25 | `nx.freeze` is a partial structural guard; attribute dictionaries stay mutable | `tests/qualification/test_networkx_stub.py` measures both halves against NetworkX itself — a frozen graph refuses a node, and a write through a filtered view reaches the base graph |
| DATA-50 | DataFusion built-ins first; a custom function needs a demonstrated gap | `queries-builtins-first` catches the call; `tests/integration/test_builtins_first.py` catches the registration by any path, by comparing a release context against a bare `SessionContext` |
| DATA-17 | Reachability is never reported as certain failure | `tests/unit/test_result_vocabulary.py` parses `queries/results.py` with `ast` and scans every classification's name, value and documentation for a word that claims a consequence |
| CORE-26, DATA-48 | A declared field is a field something reads | `tests/unit/test_declared_fields_are_read.py` scans the package's syntax tree for attribute reads and asserts every field of every query record appears among them. `Relationship.context_id` had been declared and unwritten since W1; W5 shipped two more, and this found the third |
| DATA-48 | "Applicable traversal semantics" is a claim, not a label | `tests/integration/test_two_engines_agree.py` runs a recipe that names a policy and the policy itself against one release, and asserts they return the same elements and the same relationship ids |
| CORE-08 | Published records are deeply immutable, not merely frozen | a static scan over every `CompiledRecord` subclass, plus a hashability check that catches a mutable type nested inside another record. `frozen=True` alone does not stop a `dict` field being mutated through the model, which a test demonstrates |
| CORE-09 | No normal flow bypasses validation | `no-validation-bypass`, now covering source, tests and scripts |
| CORE-11 | Every Pydantic failure maps to a stable code | the map is total over all 104 `pydantic_core.ErrorType` members, asserted in both directions, so a library upgrade fails a test rather than degrading a report |
| CORE-01, CORE-07 | `validation` depends on `domain`, never the reverse | an AST import scan that ignores `TYPE_CHECKING` blocks, with the one permitted type-only edge asserted positively so it cannot be quietly removed |
| CORE-45 | Strategies build valid data directly | `filterwarnings` promotes the Hypothesis warning to an error, and every alias is pinned to the `StringConstraints` form that triggers it. Pyrefly independently rejects `from_type` on a constrained alias |
| CORE-14 | One configured YAML 1.2 round-trip profile with explicit depth and output settings | `domain/authoring/profile.py` is the only constructor of a `YAML()`; a test pins every setting, the depth boundary on both the pre-pass and the composer, and a byte-identical round trip of a fixture in the profile's own style |
| CORE-17 | ruamel presentation objects never escape the authoring adapter | the ast-grep rule above for imports, an AST scan for the exclusion glob, and a runtime check that the adapter's plain output is exactly `str`, `int`, `float`, `bool`, `None`, `tuple` and `dict` by type identity |
| CORE-15, CORE-16 | Duplicate keys and forbidden constructs fail deterministically | one fixture per `CORE.YAML.*` code under `tests/fixtures/authoring/forbidden/`, each proving its code and its line and column; a totality test keeps the adapter's code set, the registry's YAML area and the fixture directory equal |
| CORE-18, CORE-19 | Every diagnostic says where it was seen **and how confidently** | the resolution is a value (`exact`, `path`, `parent`, `document`) recorded in every located diagnostic's `context` and rendered as `(nearest: …)` when it is not the requested path, so a fallback is visible rather than a misleading position. The hard-gate test reads the expected line and column out of the fixture |
| CORE-20 | An edit through the source and an edit through the command engine are the same edit | a Hypothesis property asserts `model_digest(apply_change_set_to_source(...)) == model_digest(build_candidate(...))` over generated models and command batches, so the two implementations cannot drift; comment survival is pinned by removal tests at the first, middle and last position |
| DATA-26 | Every field's change is classified, and the table has no default | `CHANGE_CLASSIFICATION` maps all 138 fields reachable from `Model` to a `(ChangeKind, ChangeNature)`, asserted total by reflection in `tests/unit/test_change_classification.py`. `rules/change-classification-has-no-default.yml` forbids `.get` on the three tables, because a default would answer for a field nobody classified and the totality test would keep passing. The residual is pinned by a ceiling *and* by seventeen fields that must never reach it |
| DATA-26, DATA-31 | A layout edit is not an architectural change | the gate test asserts five things in one function, four of which kill a different way of passing for the wrong reason: the models really differ, the change record is non-empty and exact, no row is `CANONICAL_SEMANTIC`, the other collections are untouched, and a negative control on the same binding *does* produce a semantic change. Three hand-run sabotages are named in the commit |
| DATA-26 | The differ agrees with the digest, both directions | a Hypothesis property asserts `field_changes(a, b) == () <=> record_digest(a) == record_digest(b)`, with `event()` reporting that 86% of generated pairs compared records and 73% had a digest move. A differ that returned nothing would satisfy one direction perfectly |
| DATA-26 | The change layer stays above the layers it composes | `rules/changes-not-imported-by-lower-layers.yml` plus `tests/unit/test_layering.py` for the half an `ignores` glob cannot state. The rule fired on real code the moment `contracts.py` grew its imports, which is what proves it works |
| DATA-28 | An alternative is derived, never descended | three refusals at three levels: `ArchitectureRelease` refuses half a relation and a parent that is the baseline; `alternative_line_breaks` reports a parent on another line; `diff_releases` refuses a cross-line pair. `AlternativeComparison` is not a `ModelChanges` and contains none, so it cannot be published as a change set by type |
| CORE-21 | Presentation never changes semantic identity | a Hypothesis property requotes, restyles, comments, reindents and reorders a rendered model and asserts the digest and an empty `semantic_delta`, with a negative control proving one changed name is detected. `COLLECTION_ORDER` is asserted total by reflection over `Model`, so a new collection field cannot be hashed until its order policy is declared |
| CORE-07 | Every validation rule catches something | each registered rule has a known-bad fixture that must trigger it, and a totality test makes a rule without one impossible to add |
| DATA-13 | An extension is an annotation nobody queries | the bound is a `Field(max_length=16)` with a uniqueness validator, and the rule that matters is enforced by an AST scan over `queries/`, `projections/` and `validation/rules/` for any read of `extensions`. The scan first proves it catches a known-bad read, and refuses to run if one of those packages is renamed away |
| DATA-44 | Arrow metadata self-describes and never carries meaning | an AST scan confines `.metadata`, `with_metadata`, `remove_metadata` and `replace_schema_metadata` to `storage/metadata.py`, and the behavioural half is stronger: a table stripped of every `architecture_toolkit.*` key produces identical records and identical digests on all eleven tables |
| DATA-12 | No Arrow union, extension, dictionary or `large_*` type in a persisted schema, and no nullable struct | a recursive walk over every declared schema, plus the conditional rule for any future nullable struct asserted alongside it and deliberately vacuous, so it starts biting the moment one is added |
| DATA-34, DATA-51 | No published release resolves an implicit latest table version | `no-implicit-latest-delta-version` for the call shape, a keyword-only `version` with no default on the Protocol and the provider, and `require_version` rejecting `True` — which `isinstance(x, int)` would accept as `1` |
| DATA-43 | One place unwraps a foreign Arrow object | an AST scan for `arro3` in any `src` module and a text scan pinning the capsule dunders to exactly `domain/capsules.py` and `storage/interchange.py` |
| CORE-53 | A type stub is qualified, not trusted | `tests/static/pyarrow_surface.py` asserts the type of every pyarrow call `storage/` makes, and `tests/qualification/test_pyarrow_stub.py` asserts the runtime truth and that every name the stub declares still exists. Three divergences are pinned *as declared*, so a corrected stub fails the build |
| DATA-20 | A Delta table version is never an architecture release | `releases-no-direct-delta` for the import boundary, plus a layering test that `deltalake` is spoken to in exactly one module. The manifest is the only thing that names a version, and a reader opens what it names |
| DATA-22 | Unchanged tables are reused rather than rewritten | an identical overwrite still creates a Delta version, so reuse is asserted as a diff of two manifests: a one-element rename moves one pin and leaves ten unchanged |
| DATA-24 | No failure exposes partial state | the fault-injection suite is parametrized over `STEP_ORDER`, so it covers every publication stage by construction and a ninth stage added without handling its failure fails the suite |
| DATA-52 | Native FFI is never enabled merely because it exists | a provider class that always raises, naming the version mismatch. Its test fails when the majors align, which is when somebody enables the rung deliberately |
| DATA-56 | Automatic schema merge is never publication behaviour | `storage.delta.write_snapshot` declares `schema_mode: Literal["overwrite"] \| None`; the `"merge"` deltalake also accepts fails `pyrefly check` rather than a review |
| DATA-58 | Vacuum cannot invalidate a retained release | the keep-list is computed from every manifest in the store and passed to `vacuum(keep_versions=...)`, so the policy and the operation cannot disagree; a negative control vacuums with an empty keep-list and asserts the damage is detected |

Type stubs (`types-networkx`, `types-jsonschema`, `types-lxml`) are dev-only typing aids with no
runtime surface, so they do not constitute an overlapping stack under DATA-32/33. `types-lxml`
pulls `soupsieve`, `types-html5lib` and `types-webencodings` transitively; all are stub or parsing
support, none is a data-processing engine.

### Installation

ast-grep is a **system tool**, not a project dependency. It stays out of `pyproject.toml` and
`uv.lock`: it is a developer tool that reads the repository, not something the package imports,
and DATA-35's one-project-one-lock rule is about the application's runtime.

Install it however you install other developer tooling (`brew install ast-grep`,
`cargo install ast-grep`, `npm i -g @ast-grep/cli`). CI fetches a pinned release binary onto the
runner in one step — see `AST_GREP_VERSION` in `.github/workflows/ci.yml`. Bump that version
deliberately and re-run `ast-grep test`, because a rule engine upgrade can change match behaviour.

## Tier 3: text, and where ripgrep fits

`scripts/check_boundaries.py` enumerates tracked files with `git ls-files` rather than walking the
tree, because the question it asks — "is this committed?" — is one git answers exactly, while a
directory walk has to reimplement ignore semantics.

Two guards added in W1 are neither ast-grep rules nor text scans, and belong to a fourth informal
tier worth naming: **the type system and the language itself**. Deep immutability is enforced by
hashability rather than by inspecting field declarations, because `hash()` answers the real
question — is anything in this tree mutable — where a declaration scan answers only whether the
*outermost* field looks immutable. Exhaustiveness over a union is enforced by `assert_never` under
Pyrefly rather than by a runtime check, because the failure then arrives before the code runs.
Reach for this tier first where it applies; it is the only one that cannot be forgotten.

**ripgrep is a system tool on the same footing as ast-grep**, and is preinstalled on the hosted
runner images this project targets. `check_boundaries.py` still uses the standard library, for a
reason that is about correctness rather than dependencies: at 64 tracked files the scan cost is
irrelevant, and `git ls-files` answers "is this committed?" exactly, where any ignore-aware walk
only approximates it.

Reach for `rg` where it genuinely wins:

- **developer-side search**, where speed and gitignore awareness matter most;
- **the W8 offline-bundle scan (PROJ-36)**, which walks a built site of many generated assets
  looking for external hosts. There the file count justifies it, and `rg --json` for
  machine-readable output, `-g` globs to select asset types and `-F` for literal matching all
  earn their place.

Prefer `rg -F` for literals, and reach for `--pcre2` only when a lookaround is genuinely required
— a pattern needing a lookaround is usually a pattern that belongs in tier 1 or 2.

## Running everything

```sh
uv run python scripts/check_schema.py          # tier 1: schemas and index
uv run python scripts/check_plan_coverage.py   # tier 1: wave partition
uv run python scripts/check_boundaries.py      # tier 3: private content, payloads, dependencies
ast-grep scan                                  # tier 2: source structure
ast-grep test                                  # tier 2: the rules themselves
```

All five run in CI on macOS ARM64 and Linux x86-64.

The three Python checkers share `scripts/_common.py`: one `ROOT`, one `load_json`, one argv-only
`run` with a mandatory timeout, and one failure epilogue. They previously disagreed about the
output stream — two wrote errors to stderr and one to stdout — so a log filter that worked for one
silently missed the other.

## What this does not establish

These checks prove the implementation respects its own stated boundaries. They say nothing about
whether a modelled architecture is correct. As `docs/agent-handoff.md` puts it: no schema
validation, rendered picture, linter run or type check alone establishes tool completeness or
real-world model correctness.
