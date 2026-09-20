# W2/W3 execution handoff — authoring adapter, semantic identity and the Arrow fabric

> **Status: executed.** This was written on 2026-09-20 as the handoff for finishing W2 and
> executing W3, and both are now complete on branch `wave-2/authoring`. The plan below is kept as
> written, because the value that survives execution is the *reasoning* — why eleven tables, why
> no nullable struct, why the table digest is defined over records — and a plan rewritten after
> the fact stops being evidence of what was decided in advance. §7 records what actually
> happened, including the three places execution departed from this plan and why.

> Read §7 first if you want the outcome; read §1–§6 for the design.

Read in this order: this document; [W2 plan](w2-authoring.md); [W3 plan](w3-arrow-fabric.md);
[core contract](../contracts/core.md) §YAML authoring and §Diagnostics;
[data contract](../contracts/data.md) §Pydantic -> Arrow, §Arrow interchange, §SnapshotProvider,
§Cross-library qualification; [agent handoff](../agent-handoff.md) M1 and M2 gates. The design
authority for wording is the Notion records `ARCH-TOOL-CORE-001` §5 and `ARCH-TOOL-DATA-001` §3,
§6A, §11B–C, §11I, §12H, §13; nothing in them contradicts what is below, and no private link
belongs in this repository.

## 1. Where things stand

| Item | State |
| --- | --- |
| Branch | `wave-2/authoring`, cut from `wave-1/commands-schemas` |
| Committed | 4 commits: semantic hash; authoring adapter + SourceMap + codes; source-located diagnostics + CLI; round-trip editing |
| Uncommitted | `tests/strategies/authoring.py` (new), `tests/property/test_authoring_properties.py` (two properties appended), `tests/strategies/__init__.py` (export). **The property run after the last fix was never executed.** See §4.1 |
| Suite | 301 tests passing at the last full run (before the uncommitted property additions) |
| Strict Pyrefly coverage | 99.62% over `src` (floor is 98) |
| Every other check in `docs/agent-handoff.md` | green at commit 4 |
| W3 | not started; plan in §5 |

Conventions that held for every commit and must keep holding: the full check list in
`docs/agent-handoff.md` before each commit; commit messages end with
`Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; PR bodies name requirement IDs,
executable checks, remaining gaps and design questions; nothing is pushed without the owner.

Two operational notes. Property tests over `full_models()` take real time; iterate with
`uv run pytest tests/property -p no:cacheprovider --hypothesis-profile=dev` and run the `ci`
profile before committing with a generous timeout (the default 120 s shell timeout is not
enough for the whole property module). Hypothesis shrinking on a genuine failure can run for
minutes silently; `-x` plus `--hypothesis-show-statistics` shows what it found.

## 2. Owner decisions already taken (do not reopen)

| Decision | Choice |
| --- | --- |
| Authoring adapter home | `src/architecture_toolkit/domain/authoring/`, inside the accepted W2 packages. Parse failures are typed `AuthoringError` values normalized in `validation/`. `import ruamel` is confined there by `rules/ruamel-only-in-authoring.yml` and an AST test |
| W3 table cut | eleven tables: `elements, relationships, interactions, references, reference_links, notation_bindings` + `interface_details, deployment_details, data_schema_details, behavior_details, requirement_details`; `Element.detail` is normalized out of `elements` |
| DATA-13 extension field | `extensions: tuple[Extension, ...]` on `Element` and `Relationship`, at most 16 entries |
| pyarrow typing | qualify `pyarrow-stubs` in the dev group first; fall back to project-owned partial stubs under `typings/pyarrow/` |

## 3. What is implemented (W2 commits 1–4)

### 3.1 Semantic identity — `domain/semantics.py` (commit `4b23ed0`)

CORE-21, DATA-27. Public API:

- `SEMANTIC_HASH_VERSION: Final[str] = "1"`; `PREIMAGE_PREFIX = "architecture-toolkit/semantic/v1\n"`;
  `EXCLUDED_FIELDS = {"content_hash"}` (stripped at every depth).
- `CollectionPolicy` (`UNORDERED`, `ORDERED_BY_ORDINAL`, `AUTHORED_ORDER`, `EXCLUDED`),
  `CollectionOrder(policy, key)`, and `COLLECTION_ORDER: Mapping[(type, field), CollectionOrder]`
  covering every tuple-typed field reachable from `Model`. `tests/unit/test_semantics.py`
  asserts the table is total by reflection, so a new collection field (W3's `extensions`) must
  be declared there before it can be hashed.
- `normalize_record`, `canonical_json`, `record_digest(record)`, `collection_digest(records)`
  (sorted record digests, order-independent by construction — the primitive W3's table digest is
  defined over), `model_digest(model)` (computed, never stored).
- `stamp_digests(model) -> Model`: fills every `content_hash` through `model_validate`, details
  before their element, idempotent.
- `SemanticDelta` / `CollectionDelta` and `semantic_delta(base, candidate)`: added, removed and
  changed identities per top-level collection, by record digest. Classification is W6's.

Decisions recorded in `docs/plans/w2-authoring.md` § Decisions taken during execution: SHA-256
over canonical JSON (sorted keys, no whitespace, UTF-8, no Unicode normalization), version in
the preimage, ordinal-bearing collections canonicalized by `ordinal` (tuple order is
presentation), `Element.aliases` excluded, `RelationshipTypeDefinition.ordered_sequence` left
for W5/W6.

Known vector: the example fixture's model digest under version 1 is pinned in
`tests/unit/test_semantics.py` (`EXAMPLE_DIGEST`). A change there means a DATA-56 migration and
a version bump, never a silent edit. `domain/registry.py`'s two module constants were annotated
in the same commit (they were two of the three coverage misses).

`tests/strategies/relations.py` gained `interactions`, `reference_links`, `notation_bindings`
and `full_models()` (every one of the six collections populated); `coherent_models()` is
unchanged.

### 3.2 Authoring adapter and SourceMap (commit `a3507ce`)

CORE-14..CORE-18. `domain/source.py`:

- `SourceLocation` moved here verbatim from `validation/diagnostics.py`, which re-exports it;
  the docstring is kept exactly as W1 published it because it is the JSON Schema description and
  the validation-report snapshot must stay byte-identical.
- `render_segments(segments) -> str` is the one path grammar (`elements[7].detail.fields[1].x`);
  `split_path` is its inverse for the semantic grammar only (identifiers may contain dots, so the
  identity grammar is never tokenized). `validation/normalize.py` renders through it
  (`semantic_segments` + `field_path`).
- `LocationResolution` (`exact`, `path`, `parent`, `document`).
- `SourceEntry(path, segments, value, key, identity_path)` and `SourceMap(source_id,
  document_id, source_digest, parser_version, profile_version, root, entries, identity_paths,
  record_paths)` with `lookup`, `lookup_identity`, `nearest`. Frozen dataclass over
  `MappingProxyType`; build metadata, not a schema family. `record_paths` holds top-level
  records only — a participant or schema field also carries an identity key, but a diagnostic
  addressed at that identity means the record.

`domain/authoring/`:

- `profile.py`: `make_yaml()` returns a fresh `YAML(typ="rt")` per call (the composer's depth
  counter is per instance and does not reset), `preserve_quotes=True`, `indent(2, 4, 2)`,
  `width=100`, `max_depth=MAX_DEPTH + 1` (the composer counts nodes, scalars included; the
  pre-pass counts collections; the bounds coincide on the same documents), `version` unset
  (setting it makes dumps emit a `%YAML 1.2` directive). `MAX_DEPTH = 16`,
  `AUTHORING_PROFILE_VERSION = "1"`, `CORE_SCHEMA_TAGS`, `PYTHON_TAG_PREFIX`, `dump_text`.
- `errors.py`: `AuthoringError(code, message, *, location, context, related)`; iterating it
  yields itself then `related`. `AUTHORING_CODES` is the adapter's copy of the registry's
  `CORE.YAML.*` area; a test asserts equality.
- `prepass.py`: `check_events(text, *, source_id)` walks `parse()` events with a frame stack and
  reports **every** finding: `UNSUPPORTED_VERSION`, `MULTIPLE_DOCUMENTS`, `DEPTH_EXCEEDED`,
  `ANCHOR`, `ALIAS`, `MERGE_KEY` (plain `<<` in key position; a quoted one is an ordinary key),
  `DUPLICATE_KEY` (found here — neither `parse` nor `compose` detects duplicates, only
  construction does, and the loader never constructs mappings), `PYTHON_TAG`, `CUSTOM_TAG`
  (any explicit tag outside the core schema, `!!binary`/`!!set`/`!!timestamp` included),
  `SYNTAX`. Positions come from event marks, 1-based.
- `plain.py`: `build_plain(node, *, source_id, constructor) -> WalkResult` walks the composed
  node tree once: scalars by resolved tag (a plain `2024-01-01` stays a string; the rt loader
  would have made a `date`), sequences to tuples, mappings to dicts, an entry with start and end
  for every node plus the key position for mapping values, identity-grammar aliases from
  `IDENTITY_KEYS`. Output types are exactly `str, int, float, bool, None, tuple, dict`
  (checked by identity in tests).
- `loader.py`: `LoadedSource(source_id, text, data, source_map)` with `json_text()`;
  `parse_source(text, *, source_id)` = pre-pass → `compose` → walk (no round-trip tree is built);
  `parse_model(loaded)` = `Model.model_validate_json` (the JSON detour is required: strict
  Python mode rejects authored enum strings and collapses list→tuple errors);
  `load_model_text`; `YamlSourceLoader(root).load(source_id) -> LoadedSource`, the
  `SourceLoader` implementation, asserted in `tests/static/protocol_conformance.py`.
- `domain/protocols.py`: `SourceLoader.load` now returns `LoadedSource` (type-only import).

`validation/codes.py`: `CodeArea.YAML` and eleven `CORE.YAML.*` specs, category
`AUTHORING_PARSE`, default claim/disposition/severity. Parse failures never enter a claim
report; `_UNREACHABLE[SCHEMA_SYNTAX]` in `pipeline.py` is untouched.
`validation/normalize.py`: `normalize_authoring_error(error)`.
`validation/diagnostics.py`: `build_diagnostic(..., source_location=None)`; the location is
**not** in the `diagnostic_id` preimage.

Guards: `rules/ruamel-only-in-authoring.yml` (+ rule test and snapshot);
`tests/unit/test_layering.py::test_ruamel_is_confined_to_the_authoring_adapter` (proves the
rule's `ignores` glob, which `ast-grep test` cannot). Fixtures: one file per code under
`tests/fixtures/authoring/forbidden/` headed `# expect: CODE line:col`, plus
`tests/fixtures/authoring/round_trip/canonical.yaml` (byte-identical round trip) and
`tests/fixtures/authoring/nested_foreign_key.yaml` (the hard-gate fixture: `submitted_by`'s
foreign key names `ghost`). Tests: `test_authoring_codes.py`, `test_authoring_profile.py`,
`test_source_map.py`. `docs/contract-enforcement.md` carries the rule row and the CORE-14/15/16/17
policy rows.

### 3.3 Source-located diagnostics and the CLI (commit `a95f495`)

CORE-19. `validation/locate.py`:

- `locate_validation_error(error, *, root, source_map)`: normalize, then for each raw location
  try `nearest(segments)`; `path` on a full match (an `extra_forbidden` uses the entry's **key**
  position), `parent` on a partial match, `document` at the root.
- `locate_diagnostic(diagnostic, source_map)`: anchor from `relationship_id` (filtered to
  `relationships.`) else `canonical_object_id`; `field_path` looked up in the identity index
  then the semantic index → `exact`; else strip the suffix after the anchor one segment at a
  time → `parent`; else the record → `exact` when no field was requested, `parent` when one was;
  else the root → `document`.
- `locate_report(report, source_map)`. Every located diagnostic carries
  `location_resolution=<value>` in `context` and keeps its `diagnostic_id`
  (`Diagnostic.model_validate(dict(d) | {...})`, never `model_copy(update=)`).

`validation/render.py`: line one gains ` (nearest: <semantic_path>)` for `parent` and
`document` resolutions. `validation/authoring.py`: `SourceValidation(outcome, diagnostics,
report, model, source_map)` and `validate_source_text(text, *, source_id, profile)`. `cli.py`
reads through it (exit 3 unreadable, 1 record or hard cross-record errors, 0 otherwise) and no
longer imports ruamel; `doctor` lists `ruamel.yaml`. Three rules gained the leaf they already
knew: `schema-references-resolve` appends `.references_element_id`, `endpoint-kinds` adds
`relationships.<id>.<side>_element_id`, `profile-version-supported` adds `profile_version`.
`tests/conftest.py` and `scripts/check_schema.py` read through the adapter, so no code path in
the repository uses `YAML(typ="safe")` any more.

Hard gate: `tests/unit/test_locate.py::test_a_nested_cross_record_failure_resolves_to_its_exact_line_and_column`
(the `ghost` foreign key resolves to line 112, column 35 of the fixture with `exact`). Also
covered: Pydantic route (`path`), unknown field → key position, missing field → `parent` with
`(nearest: elements[2])` rendered, `acyclic` → `document`, `single-parent` → record `exact`,
dotted identifiers never split, identity unchanged by locating, every diagnostic of the example
located. `tests/unit/test_cli.py` pins the exit codes and the rendered first line.
`docs/qualification.md` YAML row and `docs/toolchain.md` (ruamel 0.19.1 **does** ship
`py.typed`) were corrected.

### 3.4 Round-trip editing (commit `fae0982`)

CORE-20. `domain/authoring/render.py`: `render_record(record) -> CommentedMap` from the
JSON-mode dump with defaults and `None` omitted, `Literal` discriminators re-inserted (they carry
defaults and `exclude_defaults` drops them), frozensets sorted, scalar-only sequences in flow
style, `content_hash` never written; `render_model_text(record)`; `scalar(value)` returns a
`DoubleQuotedScalarString` for the two shapes ruamel does not round-trip plain — a string
containing U+0085 (emitted as a YAML 1.1 line break, folded to a space on reload) and a string
starting with `?` inside a flow sequence (read back as a complex key). Both were found by the
property, not by reading the specification.

`domain/authoring/editing.py`: `apply_change_set_to_source(text, change_set, *, source_id) ->
SourceEditResult(text, model, source_map, base_digest, candidate_digest, delta)`. Checks
`model_id` and `expected_base_digest` (a stale digest is `SourceEditError`, a `CommandError`
subclass) before any edit; composes one presentation tree; locates records in the **live tree**
by identity (earlier commands may have appended or removed items); mirrors `build_candidate`
per variant (`AddElement`/`AddRelationship` append `render_record`, matching flow style when
every existing item is flow; `UpdateElement` sets `name`/`description`/`aliases` in place;
`RenameElement` checks `expected_name`; `RetireElement` sets `lifecycle_state: retired`;
`RemoveRelationship` uses `_remove_item`; `UpdateDetail` deletes, key-wise merges a same-family
detail, or replaces); dumps; reparses through `parse_source`; record-validates; computes
`semantic_delta`. `_remove_item` splits the removed item's trailing comment token at its first
newline and reattaches the tail (the comment block above the next item) to the previous item's
trailing token or to the parent key's leading-comment slot when the first item goes.

`validation/authoring.py`: `SourceEditReport(edit, report)` and `edit_and_validate(text,
change_set, *, source_id, profile)` — cross-record validation located against the **new**
text. `tests/unit/test_editing.py` has one test per variant, comment preservation on removal at
first/middle/last, the stale-digest refusal, and a diagnostic caused by an edit located in the
new text. `tests/property/test_authoring_properties.py` (committed part) proves a rendered model
reloads to the same digest and that editing the source equals applying the commands
(`model_digest(edit) == model_digest(build_candidate)`).

## 4. Remaining W2 work

### 4.1 Commit 5 — presentation-invariance property and docs (in progress, uncommitted)

The working tree holds:

- `tests/strategies/authoring.py` (new): `reformatted(text)`, a composite that loads the text
  into ruamel's tree and applies drawn presentation rewrites — requoting, flow/block style,
  inserted comments (`yaml_set_comment_before_after_key`, `yaml_add_eol_comment`), reordered
  mapping keys, shuffled unordered collections (`UNORDERED_COLLECTIONS`) and ordinal-bearing
  lists (`ORDINAL_LISTS`, ordinals kept), alternate `indent`/`width` on output. `_requote`
  already carries the fix for the one real failure the property found: single-quoted style is
  only a presentation choice for **printable** text (ruamel wraps a single-quoted scalar at a C1
  control character and the reload folds the break into a space); non-printable text is
  double-quoted. The renderer never single-quotes, so the adapter was never at fault.
- `tests/property/test_authoring_properties.py`: two appended properties,
  `test_presentation_never_changes_the_semantic_digest` (CORE-21, DATA-27; `model_digest` equal
  and `semantic_delta(...).is_empty` after `reformatted`) and
  `test_a_content_change_under_the_same_presentation_is_detected` (negative control: one renamed
  element is the only `changed` identity). The negative control is what surfaced the C1 case.
- `tests/strategies/__init__.py`: exports `reformatted`.

**Next steps, in order:**

1. `uv run pytest tests/property -q -p no:cacheprovider --hypothesis-profile=dev` — expected
   green after the `_requote` fix; if the negative control still finds a second changed record,
   reproduce with the hunting approach (draw `full_models()`, `render_model_text`, `reformatted`,
   reload, compare `normalize_record` per identity) and fix the **strategy** unless the
   difference is reproducible through `render_record`/`parse_source` alone, in which case fix
   `scalar()` and add the shape to its docstring.
2. Run the `ci` profile on the property module with a long timeout (it exceeded 120 s while
   shrinking; expect one to three minutes when green).
3. Docs: `docs/contract-enforcement.md` policy rows for CORE-19 (resolution stated in every
   diagnostic; hard-gate test), CORE-20 (edit-equivalence property; comment-preservation tests)
   and CORE-21 (presentation-invariance property; `COLLECTION_ORDER` totality);
   `docs/agent-handoff.md` "Current executable state" — move the YAML adapter, SourceMap and
   canonical hash to *Implemented* and describe W2 in one line; `docs/qualification.md`
   "Semantic diff/migration" row → record-level delta at W2; `docs/plans/w2-authoring.md` —
   mark each work item *Landed* in the W1 style and extend the decisions section with: adapter
   home, the eleven codes and why parse failures never enter a claim report, node-driven plain
   data (the `date`/`HexCapsInt` finding), the fixed-point guarantee (byte identity only for a
   document in the profile's own style), the two quoting shapes, C1 single-quote limitation,
   `record_paths` top-level-only.
4. Full check list, commit: `Add the presentation-invariance property and record the W2 decisions`.

### 4.2 Commit 6 (recommended, small policy question) — reformat the example

`examples/minimal/model.yaml` is not byte-identical under the profile (its hand-wrapped flow
mappings are re-flowed at width 100); it is a fixed point after one dump. Replacing it with
`dump_text(make_yaml().load(text))` makes the shipped example byte-identical and lets
`test_the_example_is_a_fixed_point...` assert identity outright. `examples/` is outside W2's
declared packages in `reference/plan-waves.json`, so record it in the PR. Literal line numbers
to update afterwards: `tests/unit/test_cli.py` (`:87:` for `timeout_ms`), `tests/unit/
test_source_map.py` (root at 7:1, `elements` at line 12), `tests/unit/test_locate.py` (`(7, 1)`
for the document fallback), and `tests/fixtures/authoring/nested_foreign_key.yaml` is a separate
copy and stays as it is (`112:35` in `test_cli.py`).

### 4.3 Open items to state in the W2 PR

- A twelfth code `CORE.YAML.UNSUPPORTED_TAG` for non-core standard tags instead of folding
  them into `CUSTOM_TAG` (owner preference; today `CUSTOM_TAG` with `tag=` in context).
- No byte-size bound on input (CORE-14 asks for depth only).
- Located and unlocated diagnostics share an id but differ as records (context differs).
- `UpdateElement` cannot edit `extensions` (added in W3); W6 decides whether that is semantic.

## 5. W3 — Arrow fabric, in full

Requirements DATA-10..14, 34, 43..45 plus the DATA-60 rows W3 seeds. Packages `storage/`,
`domain/`, `tests/`. No Delta writing as a feature and no releases; tests may write throwaway
Delta tables under `tmp_path` to obtain arro3 objects, as `tests/qualification/test_data_stack.py`
does. Hard gate: two Arrow tables holding identical logical values with different batch
boundaries hash equal; one changed field value does not.

### 5.1 Verified facts the design rests on (probed against the lock on 2026-09-20)

Installed: pyarrow 25.0.1, deltalake 1.6.4, datafusion 54.0.0, arro3-core 0.8.3.

- `pa.Table.equals` ignores chunking; IPC bytes differ until `combine_chunks()`; `to_pylist()`
  is chunk-independent. A dictionary-encoded column breaks `equals` and schema equality;
  `pc.dictionary_decode` restores them. `schema.empty_table()` keeps schema and metadata with
  zero batches.
- Delta round trip preserves nested nullability, `timestamp[us, UTC]`, `date32`,
  `map<string,string>`, `list<struct>`, empty typed tables and **field-level** metadata, but
  **drops schema-level metadata**. Delta rejects a null in a non-nullable field at write time;
  `pa.Table.from_pylist` does not enforce nullability. A dictionary-encoded column is accepted
  and reads back as plain `string`. Delta renames list item fields to `element`, so schemas
  declare `pa.list_(pa.field("element", T, nullable=False))` up front.
- `DeltaTable.schema().to_arrow()` returns an **arro3** `Schema`; `DeltaTable.scan()` and
  `QueryBuilder().execute()` return **arro3** single-pass `RecordBatchReader`s. `pa.schema(obj)`
  and `pa.RecordBatchReader.from_stream(obj)` normalize them via the PyCapsule interface; a
  consumed arro3 reader raises `OSError: Cannot read from closed stream`. `arro3-core` ships
  `py.typed` with `ArrowSchemaExportable`/`ArrowStreamExportable` Protocols; `deltalake` ships
  `_internal.pyi`; `datafusion` is typed.
- DataFusion 54: `register_record_batches`, `from_arrow(table | reader, name=)`,
  `register_dataset`, `read_arrow`, `register_arrow`; `DataFrame.__arrow_c_stream__` and
  `execute_stream`. `register_record_batches(name, [[]])` **panics** (pyo3 `PanicException`), so
  the empty-batch synthesis in `register_snapshot` is load-bearing; `from_arrow` over an empty
  `RecordBatchReader` works and keeps the schema. Timestamps, dates, maps (`map_extract`) and
  `list<struct>` (`cardinality`) query correctly; dictionary inputs stay dictionary-typed in
  results.
- **Null-struct quirk is physical, not declarative:** `pa.Table.from_pylist` writes `''` into a
  string child of a `None` parent struct and DataFusion's `s.p` returns that `''`; after a Delta
  round trip a *nullable* child reads back NULL but a *non-nullable* child stays `''`; with
  `pa.StructArray.from_arrays(..., mask=)` the child is a real null and DataFusion returns NULL.
  Rule: the baseline persists **no nullable struct**; children of any future nullable struct are
  nullable; the matrix records both constructions.
- `pa.Table.set_column` drops nullability and field metadata; `table.cast(schema)` restores
  both (and casts a dictionary column to plain `string`). After `cast → combine_chunks →
  sort_by`, IPC bytes are identical across chunkings.
- Strict Pyrefly coverage is 99.62% with one remaining miss, `register_snapshot` (`pa.Schema`
  in its signature); pyarrow ships no `py.typed`. `pyarrow-stubs` latest is `20.0.0.20260819`
  with `requires_dist: pyarrow>=20` (installable; its changelog tracks the 20.x surface). Pyrefly
  resolves `search-path` > typeshed > `site-package-path` and auto-adds a project-root `typings/`
  to the latter. `docs/toolchain.md` still says pyarrow-stubs was rejected for a major mismatch;
  W3 records the new outcome.

### 5.2 Commit 1 — typing pre-step

1. Add `pyarrow-stubs==20.0.0.20260819` to the `dev` group, `uv lock`, run
   `uv run pyrefly check` and `uv run pyrefly coverage check --strict`. Acceptance: zero new
   errors on the surface storage uses (`schema/field/types`, `Table`, `RecordBatch`,
   `RecordBatchReader.from_batches/from_stream`, `compute.dictionary_encode/decode`, `dataset`,
   `ipc`, the `__arrow_c_*__` dunders) and `register_snapshot` no longer `[coverage-partial]`.
   CI qualifies both platforms.
2. If it misreports the 25.x surface, fall back to project-owned partial stubs
   `typings/pyarrow/{__init__,compute,ipc,dataset,fs}.pyi` (~200 lines: precise return types,
   permissive parameters, **no** module `__getattr__` so an undeclared name is a checker error)
   with `pyproject.toml` `search-path = ["typings", "src", "scripts", "."]` so the stub shadows
   the installed package and resolves the pyarrow names inside deltalake's and datafusion's own
   annotations. Guard `tests/unit/test_pyarrow_stub.py`: parse the `.pyi` with `ast` and assert
   every declared class/function/method exists on the runtime module. If search-path shadowing
   does not behave as documented, use the `typings/pyarrow-stubs/` stub-package form next.
3. Either way: annotate every new public module constant (`ELEMENTS: Final[TableSchema] = …`),
   record the measured figure and the decision in `docs/toolchain.md` (replacing the "pyarrow
   remains uncovered" paragraph), and raise `--fail-under` after commit 6 if earned.

Checks: `pyrefly check`, `pyrefly coverage check --strict --fail-under 98`, ruff, `pytest -m unit`.

### 5.3 Commit 2 — domain additions

- `domain/identifiers.py`: `TABLE_ID_PATTERN = ^[a-z][a-z0-9_]{2,63}$` → `TableId`;
  `EXTENSION_NAMESPACE_PATTERN = ^[a-z][a-z0-9]*(\.[a-z][a-z0-9]*)+$` → `ExtensionNamespace`;
  both in `__all__` and in `tests/strategies/ids.py::STRATEGY_BY_ALIAS` (set-equality test).
- `domain/extensions.py` (new, DATA-13): `MAX_EXTENSIONS_PER_RECORD = 16`,
  `MAX_EXTENSION_VALUE_LENGTH = 1024`; `Extension(CompiledRecord)(namespace: ExtensionNamespace,
  key: str[1..64], value: str[..1024])`; a helper that rejects duplicate `(namespace, key)`.
  Docstring carries the rule: an extension is an annotation nobody queries; the moment a query,
  projection or rule reads one it graduates to a typed field via a DATA-56 migration.
- `domain/model.py`: `Element.extensions: tuple[Extension, ...] = Field(default=(),
  max_length=MAX_EXTENSIONS_PER_RECORD)` placed before `content_hash`; same on `Relationship`;
  a `model_validator` for unique keys on each.
- `domain/semantics.py`: `COLLECTION_ORDER` entries `(Element, "extensions")` and
  `(Relationship, "extensions")` as `UNORDERED` with key `("namespace", "key")`. The totality
  test fails until they exist.
- `domain/capsules.py` (new): `ArrowSchemaExportable` (`__arrow_c_schema__`),
  `ArrowArrayExportable` (`__arrow_c_array__(requested_schema=None)`), `ArrowStreamExportable`
  (`__arrow_c_stream__(requested_schema=None)`), `@runtime_checkable`. Kept out of
  `protocols.py` so `tests/unit/test_protocols.py`'s eight-boundary registry stays untouched.
- `domain/providers.py` (new): `Materialization(StrEnum)` (`materialized`, `streaming`,
  `lazy_dataset`); `SnapshotProviderDescription(CompiledRecord)(provider_type, materialization,
  preserves_typed_empties: bool, library_versions: tuple[tuple[str, str], ...],
  native_ffi_enabled: bool = False)` — deterministic, no timestamps or paths.
- `domain/protocols.py`: fill `SnapshotProvider`:
  `describe(self) -> SnapshotProviderDescription`,
  `schema_for(self, table_id: TableId, *, version: int) -> ArrowSchemaExportable`,
  `open(self, table_id: TableId, *, version: int) -> ArrowStreamExportable`. Keep the
  "never implicit latest" sentence. `tests/unit/test_protocols.py`'s `Conforming` and
  `WrongSignature` gain `describe`/`open`; the parameter is renamed `table_id`.
- Regenerate schemas (`uv run architecture schema --write`; `extensions` defaults to `()` so
  `check_schema.py` job 4 still passes); `tests/static/pydantic_patterns.py` gains the
  bounded-tuple `Field(max_length=...)` pattern and `match`/`assert_never` routing over the
  detail union; `tests/unit/test_extension_policy.py` (DATA-13 guard: `MaxLen(16)`, 17 entries
  and a 1025-char value fail, duplicate keys fail, an AST scan finds no
  `Attribute(attr="extensions")` in `queries/`, `projections/`, `validation/rules/`, with a
  known-bad snippet proving the scan catches one). W2's presentation-invariance property gains
  extension reordering as an invariance (add `"extensions"` to `UNORDERED_COLLECTIONS` in
  `tests/strategies/authoring.py` and extensions to `full_models()`).

Checks: `pytest -m "unit or property"`, `check_schema.py`, `ast-grep scan`, `pyrefly check`,
`architecture validate examples/minimal/model.yaml`.

### 5.4 Commit 3 — schemas, metadata policy, interchange

`storage/errors.py`: `StorageError`, `UnknownTableError(KeyError)`, `SchemaViolation`,
`TableSetIntegrityError`, `ConsumedStreamError`.

`storage/schemas.py` (DATA-10/11/12): `STORAGE_SCHEMA_VERSION: Final[str] = "1.0.0"` (the
DATA-56 migration anchor); `TableRole` (entity, relation, link, detail); `FieldRole` (identity,
foreign_key, vocabulary, digest, extension, owned); the type conventions named once —
`IDENTIFIER/VOCABULARY/TEXT/DIGEST = pa.string()`, `COUNT = pa.int64()` (**int64 for every
integer**; one integer type in the tested intersection, no literal casts in W5 recipes),
`FLAG = pa.bool_()`, `INSTANT = pa.timestamp("us", tz="UTC")`, `DAY = pa.date32()`,
`BASELINE_TYPES`; `list_of(item)` = `pa.list_(pa.field("element", item, nullable=False))`;
`field(name, dtype, *, role, nullable=False)` attaching role metadata;
`TableSchema(table_id, role, key_fields, schema, record_type)` frozen dataclass (holds a
`pa.Schema`, so not a `CompiledRecord`) with `bare()` (every `architecture_toolkit.*` key
removed — what Delta hands back); the eleven `Final` constants, `TABLE_IDS` (fixed order),
`TABLE_SCHEMAS` (`MappingProxyType`), `DETAIL_TABLE_BY_FAMILY` (five entries), `schema_for`.

Schemas (`S` string, `I` int64, `nn` non-nullable, `?` nullable; every list is
`list<element: T nn>` and itself `nn`; `content_hash S nn` role `digest` last on every table):

- Shared structs, all **non-nullable**: `status = struct<design_disposition, implementation_state,
  technical_qualification, client_acceptance, evidence_review: S nn>`;
  `extensions = list<struct<namespace S nn, key S nn, value S nn>>`;
  `subject = struct<subject_kind S nn, element_id S ?, relationship_id S ?, field_path S ?,
  release_id S ?>` (`ReferenceTarget` flattened; no Arrow union).
- `elements` (entity; key `model_id, element_id`): element_id, model_id (identity); kind_id
  (vocabulary); name S nn; description S ?; lifecycle_state (vocabulary); aliases list<S>
  (persisted, hash-excluded); status; extensions; content_hash. **No `detail` column.**
- `relationships` (relation; key `model_id, relationship_id`): relationship_id, model_id;
  relationship_type_id (vocabulary); source_element_id, target_element_id S nn (foreign_key);
  context_id S ? (foreign_key); description S ?; extensions; content_hash.
- `interactions` (entity; key `model_id, interaction_id`): interaction_id, model_id; name S nn;
  interaction_kind (vocabulary); description S ?; participants list<struct<element_id S nn,
  participant_role S nn, ordinal I nn>> (authored order kept physically); moved_object_ids
  list<S> (foreign_key); content_hash.
- `references` (entity; key `model_id, reference_id`): reference_id, model_id; reference_kind
  (vocabulary); title S nn; locator S ?; authority S ?; content_hash.
- `reference_links` (link; key `model_id, link_id`): link_id, model_id; reference_id S nn
  (foreign_key); subject; link_role (vocabulary); note S ?; content_hash.
- `notation_bindings` (link; key `model_id, binding_id`): binding_id, model_id; subject;
  notation (vocabulary); notation_type S nn; notation_object_id S nn; view_id S ? (foreign_key);
  mapping_profile_version S nn; projection_artifact_id S ? (foreign_key); link_target S ?;
  content_hash.
- `interface_details` (detail; key `element_id`) — the DATA-11 worked example: element_id S nn
  (identity); transport struct<protocol S nn, interaction_mode S nn, serialization S nn> nn
  (owned); authentication_description S ?; request_schema_id S ? (foreign_key);
  response_schema_id S ? (foreign_key); delivery_semantics S nn (vocabulary); timeout_ms I ?;
  idempotency_description S ?; content_hash.
- `deployment_details` (detail; key `element_id`): element_id; environment S nn;
  deployment_node_id, software_instance_id, configuration_artifact_id S ? (foreign_key);
  content_hash.
- `data_schema_details` (detail; key `element_id`): element_id; fields list<struct<field_id,
  field_name, data_type, nullability, cardinality S nn, key_membership list<S> nn (sorted on
  write), references_element_id S ?, references_field_id S ?, ordinal I nn>>; content_hash.
- `behavior_details` (detail; key `element_id`): element_id; nodes list<struct<node_id,
  node_type, name S nn, ordinal I nn, participant_element_id S ?>>; transitions
  list<struct<transition_id, source_node_id, target_node_id S nn, guard S ?, ordinal I nn>>;
  content_hash.
- `requirement_details` (detail; key `element_id`): element_id; category, applicability,
  verification_method S nn (vocabulary); applicability_note S ?; acceptance_criterion_ids
  list<S> (foreign_key); content_hash.

Detail tables carry no `model_id` (exact bijection with the detail records; one model per
release). Invariants asserted by `tests/unit/test_storage_schemas.py`: no union, extension,
dictionary, large_* or non-`us`/non-UTC timestamp type anywhere (recursive); every list and list
item non-nullable; every child of a nullable struct nullable (vacuous — a second assertion pins
that no nullable struct exists); every top-level field has a `FieldRole`; `content_hash` last,
non-null, digest; key fields exist and are non-null identity; `set(DETAIL_TABLE_BY_FAMILY)`
equals the five element-attachable families; the `interface_details` field list is pinned
literally; `BASELINE_TYPES` contents; `TABLE_IDS` order.

`storage/metadata.py` (DATA-44) — the **only** reader of `.metadata`: keys
`architecture_toolkit.{storage_schema_version, table_id, table_role, toolkit_version}` at schema
level and `architecture_toolkit.role` at field level; `SchemaDescription(CompiledRecord)` (what
self-description says; never consulted for meaning); `describe(schema, *, table_id, role)`,
`strip(schema)`, `read_description(schema)`, `reattach(table, expected)` =
`table.cast(expected.bare()).replace_schema_metadata(...)` — what readers do because Delta
drops schema-level keys. Guard `tests/unit/test_metadata_policy.py`: an AST scan finds
`.metadata`/`with_metadata`/`remove_metadata`/`replace_schema_metadata` attribute access only in
`storage/metadata.py` (excluding `importlib.metadata`), with a known-bad snippet; the
behavioural half is in commit 4 (stripped or bogus metadata → identical records and digests).

`storage/interchange.py` (DATA-34/43) — the only module that spells `__arrow_c_*__` or `arro3`:
`as_schema(obj) -> pa.Schema`; `as_reader(obj) -> pa.RecordBatchReader` (reader → itself;
`pa.Table` → `from_batches(schema, batches_for_registration(table))`; `pa.RecordBatch` → one
batch; anything else → `RecordBatchReader.from_stream(obj)`; `getattr(obj, "closed", False)` →
`ConsumedStreamError` before touching the capsule); `as_table(obj)` (`pa.table(obj)`; consumes
single-pass readers); `empty_batch(schema)`; `empty_reader(schema)` (zero batches; valid for
`from_arrow`, **not** for `register_record_batches`); `batches_for_registration(table)`
(`to_batches()` or `[empty_batch(schema)]`). `tests/unit/test_layering.py` extended: `arro3`
banned in `domain/**`; `__arrow_c_` only in `domain/capsules.py` and `storage/interchange.py`;
`arro3` in no `src` module.

`tests/qualification/test_arrow_interchange.py` (markers `qualification` + `interop`), the arro3
half: `compile_tables(minimal)` written to Delta under `tmp_path` (commit 4 provides
`compile_tables`; in commit 3 use hand-built tables from the registry schemas);
`as_schema(DeltaTable(loc, version=0).schema().to_arrow())` equals `TableSchema.bare()`
ignoring metadata; `as_table(dt.scan())` normalizes and `canonical_table` equals the written
canonical table byte-for-byte (IPC) — if the arro3 reader's schema differs by type (e.g.
large_string) that is a real matrix finding and a strict xfail with the upstream reason
(CORE-52), not a workaround; `QueryBuilder` reader likewise; a consumed arro3 reader →
`ConsumedStreamError` (the raw `OSError` pinned as upstream behaviour); pyarrow reader and Table
into `SessionContext.from_arrow` give equal query results; an empty reader via `from_arrow`
gives `count(*) = 0` with the schema intact; `register_record_batches(name, [[]])` panics
(pinned, narrowed to the pyo3 `PanicException`).

### 5.5 Commit 4 — mappings, table sets, digests (hard gate)

`storage/mappings.py` (DATA-14): `type Row = dict[str, object]` (JSON-ready);
`TableMapping[R](table, adapter: TypeAdapter[tuple[R, ...]], to_row: Callable[[R], Row],
from_row: Callable[[Row], Row])` with `to_arrow(records) -> pa.Table` (explicit field-by-field
rows, never `model_dump`; raises `ValueError("call stamp_digests first")` when any
`content_hash` is `None`), `rows_from_arrow(source)`, `from_arrow(source) -> tuple[R, ...]` =
`adapter.validate_json(json.dumps(rows))` (the established JSON path: full error locations,
enum-by-value, list → tuple/frozenset); the eleven mapping constants, `MAPPINGS`,
`mapping_for(table_id)`; `TableSet(model_id, schema_version, profile_version,
storage_schema_version, tables: Mapping[TableId, pa.Table])` with `__getitem__` and
`with_tables(replacements)`; `compile_tables(model) -> TableSet` (calls `stamp_digests` first,
routes each element's detail with `match … case InterfaceDetail(): … case _: assert_never(…)`
so a sixth element-attached family fails `pyrefly check` — the family cut becomes structural;
empty collections → `schema.empty_table()`); `assemble_model(table_set) -> Model`;
`check_nullability(table, expected)` → `SchemaViolation` (Arrow does not enforce nullability;
Delta does at write; the mapping enforces it on read).

Reverse-mapping rules (`from_row`, then `adapter.validate_json`): `None` in a nullable scalar
stays `None`; a null in a non-nullable column is a `SchemaViolation` before any row is built;
`[]` → `()`/`frozenset()` through JSON mode; `subject` drops children whose value is `None` and
keeps `subject_kind` (the discriminator selects the variant; `extra="forbid"` rejects a non-null
slot that should have been null); `key_membership` list → frozenset; `detail_family` is not a
column and is injected from the table; metadata is never read; row order is preserved in
memory, so `assemble_model(compile_tables(m)) == stamp_digests(m)` structurally; across a
storage boundary that may reorder rows (`scan()`) the assertion is `model_digest` equality.
`assemble_model`: rows from all eleven tables → `details_by_element` across the five detail
tables (a second row for one `element_id`, within or across tables → `TableSetIntegrityError`)
→ attach to element rows → leftovers are orphans → error → every row's `model_id` equals the
TableSet's → one `Model.model_validate_json(...)` re-running every record-local validator.

`storage/digests.py` (DATA-45): `table_semantic_digest(table_id, source) -> SemanticDigest`
**defined** as `collection_digest(mapping_for(table_id).from_arrow(source))` — chunk, dictionary
and metadata independence hold by construction and W4's manifest per-table digest equals the
domain digest (one implementation, the DATA-27 rationale); `table_set_digests(table_set)` in
`TABLE_IDS` order; `canonical_table(table_id, source) -> pa.Table` = `cast(bare schema) →
combine_chunks → sort_by(key_fields) → strip metadata` — the physical normal form for equality
assertions and W4's read-back step, **not** a digest input.

Tests: `tests/unit/test_storage_mappings.py` (per table: every Optional `None` and every
collection empty; fully populated incl. all four `subject` variants, sorted `key_membership`,
extensions on an element and a relationship, `timeout_ms` 0 and 600000;
`from_arrow(to_arrow(rs)) == rs`; `to_arrow(()).schema.equals(schema, check_metadata=True)`
with 0 rows; `check_nullability` raises; a stray non-null `subject` slot raises; unstamped
records raise; `compile_tables(example)` yields eleven tables with detail rows in the right
table and `assemble_model(...) == stamp_digests(model)`); `tests/unit/test_table_set_integrity.py`
(duplicate detail within/across tables, orphan detail, foreign `model_id`);
`tests/unit/test_storage_properties.py` — `@given(full_models())`
`assemble_model(compile_tables(m)) == stamp_digests(m)` and `table_set_digests` equals the
domain `collection_digest` per collection; **hard gate**
`test_chunk_layout_never_changes_the_digest`: draw batch boundaries, rebuild each table via
`pa.Table.from_batches` with those slices, assert `table_semantic_digest` equal for all eleven,
then a drawn `RenameElement` (`assume(new_name != old)`) changes the `elements` digest; a
deterministic example with `[[a],[b,c]]` vs `[[a,b],[c]]`; metadata independence. Run the
property once locally with `--hypothesis-profile=deep`.

### 5.6 Commit 5 — materialized provider

`storage/snapshot.py` (DATA-34): `require_version(version) -> int` (exactly the existing check
`type(version) is not int or version < 0` → the same `ValueError` message; rejects `True`);
`MaterializedPyArrowSnapshotProvider(locations: Mapping[str, Path | str])` with `describe()`
(the four libraries and versions, `native_ffi_enabled=False`), `read(table_id, *, version) ->
pa.Table` (`DeltaTable(location, version=require_version(version)).to_pyarrow_table()`),
`schema_for` (the materialized table's schema — what storage holds; W4 compares it to the
registry via `bare()`), `open` → `RecordBatchReader.from_batches(schema,
batches_for_registration(table))` (deliberately the **synthesized** empty batch, because this
provider exists to feed `register_record_batches`, which panics on `[[]]`), `register(context,
name, table_id, *, version) -> pa.Schema`. `storage/datafusion_adapter.register_snapshot` keeps
its signature, docstring intent, version check, empty-batch synthesis and return value; its body
becomes `MaterializedPyArrowSnapshotProvider({name: location}).register(context, name, name,
version=version)`; `tests/qualification/test_data_stack.py` passes untouched.
`ArrowStreamSnapshotProvider` and `PyArrowDatasetSnapshotProvider` stay W4 qualification items.

Tests: `tests/unit/test_snapshot_provider.py` (`require_version` matrix over `-1, True, 1.0,
"0", None`; `describe()` lists the locked versions; unknown table → `UnknownTableError`); the
provider half of `test_arrow_interchange.py` (`open()` yields one empty batch for an empty
table; `schema_for` equals the read table schema; `register` reproduces `register_snapshot`);
`tests/static/protocol_conformance.py`: `_provider: SnapshotProvider =
MaterializedPyArrowSnapshotProvider({})` plus `ArrowSchemaExportable`/`ArrowStreamExportable`
assignments from `pa.schema([])`, `pa.table({})`, a pyarrow reader and arro3 `Schema`/
`RecordBatchReader`; the existing `MaterializedProvider` fixture updated to three methods.
`ast-grep scan` covers the new `DeltaTable(...)` call (`version=` rule).

### 5.7 Commit 6 — compatibility matrix seed and decisions

`tests/qualification/test_arrow_matrix.py` (DATA-60 + per-case requirement markers): a
`MatrixCase(case_id, requirements, schema, rows, key)` parametrized over string IDs/vocabulary;
booleans/integers; nullable scalars; **UTC microsecond instants and `date32`** (a synthetic
Pydantic record with `AwareDatetime`/`date`, JSON-mode round trip via `isoformat` — the domain
has no such field yet); non-null struct; list of struct; nested nullable-in-list; **nullable
struct via `from_pylist` vs `StructArray.from_arrays(mask=)`** (records the DataFusion
child-extraction quirk under both; `to_pylist` gives `None` in both); empty typed table; two
chunkings; **dictionary encoding** (`Table.equals` False but `canonical_table` and digest equal;
Delta accepts and reads back plain `string`; DataFusion keeps dictionary in results);
schema/field metadata (field-level survives Delta, schema-level dropped and `metadata.reattach`
restores it); RecordBatchReader/C stream via `from_arrow`; list item naming `element` equal on
readback. Each case runs Pydantic → Arrow → stage → Pydantic and records
`record_property("provider", description.model_dump_json())` for W9.

Docs: `docs/toolchain.md` (typing outcome, coverage figure), `docs/qualification.md`
(Arrow/Delta and Snapshot provider rows), `docs/contract-enforcement.md` (DATA-13/DATA-44 guard
rows), `docs/plans/w3-arrow-fabric.md` "Decisions taken during execution" (table cut, int64, no
nullable struct, detail tables without `model_id`, digest definition, typing route,
list-item naming), `docs/agent-handoff.md` current state. `--fail-under` raised if earned. Full
CI list from `.github/workflows/ci.yml`.

Hand-off to W4: `TableSet`, `table_set_digests`, `canonical_table`,
`MaterializedPyArrowSnapshotProvider(locations)` (W4 builds `locations` from the manifest),
`interchange.as_reader/as_table/empty_reader`, `metadata.reattach`, the `MatrixCase` harness
(W4 adds Delta-version, migration vN→vN+1 and provider-ladder rows), `SnapshotProviderDescription`.

### 5.8 W3 risks to carry into the PR

- Stub shadowing / `pyarrow-stubs` accuracy is the schedule risk; it is isolated in commit 1
  with the fallback ladder. Rejected alternatives: `replace-untyped-imports-with-any` (turns
  every annotation into `Any`, exactly what `[coverage-partial]` counts) and wrapper classes
  around pyarrow (a second Arrow API).
- Delta drops schema-level metadata: handled by `reattach`; the matrix pins the asymmetry so a
  deltalake upgrade that starts preserving it is noticed.
- arro3 reader schema inequality vs the written schema: most likely field metadata and list
  item naming; assert against `bare()` with `check_metadata=False` after the cast.
- int64 everywhere is reversible in W3 only; after W4 it is a DATA-56 migration.
- `schema_for` on the materialized provider materializes the table to read its schema —
  acceptable for the permanent fallback; W4's providers read `DeltaTable.schema().to_arrow()`
  through `as_schema`.

## 6. Verification, end to end

1. W2 hard gate: `uv run pytest tests/unit/test_locate.py -q`; then
   `uv run architecture validate tests/fixtures/authoring/nested_foreign_key.yaml` prints a
   four-line block whose first line ends `:112:35` and exits 1.
2. Forbidden constructs: `uv run architecture validate tests/fixtures/authoring/forbidden/<any>.yaml`
   exits 3 with the fixture's expected code.
3. Presentation invariance and edit equivalence: `uv run pytest tests/property -q
   -p no:cacheprovider` (ci profile; allow several minutes), and once with
   `--hypothesis-profile=deep`.
4. W3 hard gate: `uv run pytest tests/unit/test_storage_properties.py -q` — equal digests
   across chunkings; a changed `name` differs.
5. Interchange and matrix: `uv run pytest -m "qualification or interop" -q`;
   `.runtime/qualification/requirement-evidence.json` lists CORE-14..21, DATA-27, DATA-10..14,
   34, 43..45, 60 with `passed`.
6. After every commit, the list in `docs/agent-handoff.md`: `uv sync --locked --all-groups`,
   `ruff check .`, `ruff format --check .`, `pyrefly check`, `pyrefly coverage check --strict
   --fail-under 98`, `pytest`, `scripts/check_schema.py`, `scripts/check_plan_coverage.py`,
   `scripts/check_boundaries.py`, `ast-grep scan`, `ast-grep test`, `architecture validate
   examples/minimal/model.yaml`, `mkdocs build --strict`. CI runs the same on ubuntu and macos-14.


## 7. What actually happened

Every work item in §4 and §5 landed. The suite is 561 tests; strict Pyrefly coverage is 100.00%
over `src`; both hard gates hold. Seven commits followed this document:

| Commit | Scope |
| --- | --- |
| `cd6df82` | W2 step 5 — the presentation-invariance property, the emitter fix it found, and the W2 decisions |
| `b504d20` | the example-reformat question, answered against reformatting |
| `d50303e` | W3 step 1 — `pyarrow-stubs` adopted and qualified |
| `51305c4` | W3 step 2 — `extensions`, the Arrow capsule Protocols, the provider description |
| `923494e` | W3 step 3 — the eleven schemas, the metadata policy, the interchange layer |
| *(step 4)* | the mappings, table sets and digests, with the M2 hard gate |
| *(step 5)* | the materialized `SnapshotProvider` |
| *(step 6)* | the compatibility matrix and the decision records |

### Three departures from this plan

**The presentation property found a defect in the adapter, not in the strategy.** §4.1 anticipated
a failure and said to fix the *strategy* unless the difference was reproducible through
`render_model_text` alone. It was: ruamel's double-quoted emitter drops the line-continuation
backslash on a split it did not make at a space, so a scalar wrapped just after an escape sequence
gains a space nobody authored — reachable at the profile's own width with a 93-character prefix, a
control character and a later space. The fix is `profile._SafeRoundTripEmitter`, which withholds
that one split; ordinary wrapping is untouched, and all 67 characters the emitter escapes are
covered by a parametrized test.

**The example was not reformatted.** §4.2 recommended replacing `examples/minimal/model.yaml` with
the profile's own output so the fixed-point test could assert byte identity. Measured, the output
is worse than the input: trailing whitespace on fifteen lines, `guard:` separated from its value by
a line break, and one line still 101 columns wide. The example is the first document a reader
sees, and `canonical.yaml` already proves byte identity for a document in the profile's own style,
so the question is answered against reformatting rather than left open. Recorded in `b504d20`.

**`pyarrow-stubs` needed three suppressions, not none.** §5.2 set "zero new errors" as the
acceptance bar and named a fallback to project-owned stubs. The stub is accurate enough to take
strict coverage from 99.62% to 100.00%, and it misreports three things against pyarrow 25.0.1:
`Table.equals` is declared as returning a `Table`, `pyarrow.compute.dictionary_decode` is absent,
and `pa.schema()`'s capsule overload is missing. The fallback was not taken, because replacing an
almost-right stub with a partial hand-written one would have traded three known divergences for an
unknown number. Instead each is pinned *as declared* in `tests/static/pyarrow_surface.py` and
asserted against the runtime in `tests/qualification/test_pyarrow_stub.py`, so a corrected stub
release fails the build and the workaround is removed deliberately.

### Two refinements worth knowing about

**The eleven table digests are not a decomposition of the model digest.** §5.5 said
`table_set_digests` equals the domain `collection_digest` per collection. It does for ten of the
eleven; `elements` is the exception, because detail is normalized out of it, so its digest covers
elements without detail. That turns out to be the useful behaviour rather than a compromise: a
per-table digest answers *which tables must be republished*, which is what DATA-21's reuse gate
needs, while `model_digest` answers *is this the same model*. W4 records both. Stated in
`storage/digests.py` and asserted in `tests/unit/test_storage_properties.py`.

**`check_nullability` became two functions.** §5.5 gave it three jobs — nulls, wrong types and
unknown columns. It is `check_nullability` and `check_columns`, because "this table has the wrong
columns" and "this column has a null it should not" are different failures and a caller reading
the message should not have to work out which one happened.

### Open items carried into W4

- The `CORE.YAML.UNSUPPORTED_TAG` code from §4.3 is still an owner preference, not a decision.
- `UpdateElement` still cannot edit `extensions`; W6 decides whether an extension edit is a
  semantic change.
- `--fail-under` was raised from 98 to 100, the measured figure, rather than deferred. The
  argument that decided it: at 98 a partial annotation sits unnoticed until two percent of the
  package has accumulated them, while at 100 the first one fails in the change that introduced
  it. If W4 meets a genuinely untypable surface, lowering the floor is a decision with a recorded
  reason — which is the conversation that should happen — not a silent slide.
- Historical reproducibility is the one §11I dimension the matrix does not cover, because it needs
  several published releases. W4 extends `tests/qualification/test_arrow_matrix.py` rather than
  starting a second matrix.
