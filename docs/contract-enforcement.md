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
| CORE-08 | Published records are deeply immutable, not merely frozen | a static scan over every `CompiledRecord` subclass, plus a hashability check that catches a mutable type nested inside another record. `frozen=True` alone does not stop a `dict` field being mutated through the model, which a test demonstrates |
| CORE-09 | No normal flow bypasses validation | `no-validation-bypass`, now covering source, tests and scripts |
| CORE-11 | Every Pydantic failure maps to a stable code | the map is total over all 104 `pydantic_core.ErrorType` members, asserted in both directions, so a library upgrade fails a test rather than degrading a report |
| CORE-01, CORE-07 | `validation` depends on `domain`, never the reverse | an AST import scan that ignores `TYPE_CHECKING` blocks, with the one permitted type-only edge asserted positively so it cannot be quietly removed |
| CORE-45 | Strategies build valid data directly | `filterwarnings` promotes the Hypothesis warning to an error, and every alias is pinned to the `StringConstraints` form that triggers it. Pyrefly independently rejects `from_type` on a constrained alias |
| CORE-07 | Every validation rule catches something | each registered rule has a known-bad fixture that must trigger it, and a totality test makes a rule without one impossible to add |

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
