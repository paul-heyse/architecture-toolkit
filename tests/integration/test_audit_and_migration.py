"""Storage audit as evidence, and explicit versioned migrations (DATA-55, DATA-56, DATA-57)."""

import pyarrow as pa
import pytest
from deltalake.exceptions import DeltaError

from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.semantics import model_digest, semantic_delta, stamp_digests
from architecture_toolkit.releases.audit import attempts_for, changed_row_counts, table_audit
from architecture_toolkit.releases.errors import MigrationError
from architecture_toolkit.releases.migration import (
    MIGRATIONS,
    Migration,
    apply_migration,
    historical_replay,
    migration_for,
)
from architecture_toolkit.releases.reader import read_model
from architecture_toolkit.releases.store import ReleaseStore
from architecture_toolkit.storage import delta
from architecture_toolkit.storage.constraints import (
    ROW_LOCAL_CONSTRAINTS,
    apply_constraints,
    columns_of,
)
from architecture_toolkit.storage.schemas import STORAGE_SCHEMA_VERSION, TABLE_IDS, schema_for
from tests.integration.conftest import Publisher, rename_first_element

# -- DATA-57: history and CDF are storage evidence ------------------------------------------------


@pytest.mark.integration
@pytest.mark.requirement("DATA-57", "DATA-53")
def test_history_traces_a_table_version_to_the_attempt_that_wrote_it(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """Traceability in the direction an operator asks for it."""
    manifest = publish_release("rel-0001", example_model, expected_parent=None)
    audits = table_audit(store, "elements", version=0)
    assert audits[0].operation == "WRITE"
    assert audits[0].publication_attempt_id == "rel-0001"
    assert audits[0].provenance["model_id"] == "sample-service"

    by_table = attempts_for(store, manifest)
    assert by_table["elements"] == ("rel-0001",)
    assert set(by_table) == set(TABLE_IDS)


@pytest.mark.integration
@pytest.mark.requirement("DATA-57")
def test_the_change_feed_cross_checks_the_semantic_diff(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """§11H's actual use for CDF: verify which rows a storage operation changed.

    A rename is one semantic change and a full-snapshot overwrite of ten rows, so the two numbers
    are *expected* to differ. That is the point — the storage log is not the change narrative, and
    a test that asserted they matched would be asserting the confusion DATA-57 forbids.
    """
    publish_release("rel-0001", example_model, expected_parent=None)
    renamed = rename_first_element(example_model, "Renamed for the feed")
    publish_release("rel-0002", renamed, expected_parent="rel-0001")

    counts = changed_row_counts(store, "elements", base_version=0, candidate_version=1)
    assert counts, "the change feed reported nothing for a table that was rewritten"
    assert sum(counts.values()) > 0

    delta_records = semantic_delta(stamp_digests(example_model), stamp_digests(renamed))
    changed = [c.changed for c in delta_records.collections if c.collection == "elements"]
    assert changed == [(example_model.elements[0].element_id,)]
    # One architectural change; more than one row touched by storage. Different questions.
    assert sum(counts.values()) >= len(changed[0])


@pytest.mark.integration
@pytest.mark.requirement("DATA-57")
def test_a_commit_audit_cannot_be_mistaken_for_a_change_record(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """Typed so the confusion DATA-57 forbids is not expressible."""
    publish_release("rel-0001", example_model, expected_parent=None)
    audit = table_audit(store, "elements", version=0)[0]
    fields = set(vars(audit)) if hasattr(audit, "__dict__") else set(audit.__slots__)
    assert fields == {"version", "operation", "provenance"}
    assert not fields & {"added", "removed", "changed", "collections"}


# -- DATA-55: constraints are row-local -----------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("DATA-55")
def test_every_declared_constraint_mentions_only_its_own_columns() -> None:
    """The boundary that matters: nothing cross-record ever joins these.

    Endpoint validity, referential rules, graph semantics and evidence requirements all need
    context one row does not have, and §11G names each of them as staying an application
    validation.
    """
    for table_id, predicates in ROW_LOCAL_CONSTRAINTS.items():
        columns = columns_of(table_id)
        for name, predicate in predicates.items():
            mentioned = {
                word.strip("(),")
                for word in predicate.replace("'", " ").split()
                if word.strip("(),").isidentifier()
            }
            foreign = {word for word in mentioned if word.islower()} - columns - _SQL_WORDS
            assert not foreign, f"{table_id}.{name} mentions {foreign}, which is not row-local"


_SQL_WORDS = frozenset({"is", "null", "or", "and", "not", "like"})


@pytest.mark.integration
@pytest.mark.requirement("DATA-55")
def test_delta_enforces_a_row_local_constraint_and_the_engine_says_why(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """The reason to use a check constraint at all: the engine refuses the write, not us."""
    publish_release("rel-0001", example_model, expected_parent=None)
    location = store.table_location("interface_details")
    applied = apply_constraints(location, "interface_details", version=0)
    assert "timeout_ms_is_not_negative" in applied
    assert "content_hash_is_a_sha256_digest" in applied

    good = delta.read_version(location, version=delta.tip(location))
    rows = good.to_pylist()
    rows[0]["timeout_ms"] = -1
    bad = pa.Table.from_pylist(rows, schema=good.schema)
    # The engine's own refusal, named: `DeltaError` rather than a bare `Exception`, so a write
    # that failed for an unrelated reason would not be mistaken for the constraint working.
    with pytest.raises(DeltaError, match=r"failed validation check"):
        delta.write_snapshot(location, bad, commit_metadata={})


@pytest.mark.integration
@pytest.mark.requirement("DATA-55")
def test_applying_constraints_twice_is_harmless(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    publish_release("rel-0001", example_model, expected_parent=None)
    location = store.table_location("references")
    first = apply_constraints(location, "references", version=0)
    second = apply_constraints(location, "references", version=delta.tip(location))
    assert first == second


# -- DATA-56: explicit versioned migrations -------------------------------------------------------


def _add_a_column(table_id: str, table: pa.Table) -> pa.Table:
    """The synthetic 1.0.0 -> 1.1.0 step: one nullable column, filled with a marker."""
    del table_id
    return table.append_column(
        pa.field("migrated_note", pa.string(), nullable=True),
        pa.array(["migrated"] * table.num_rows, type=pa.string()),
    )


# `from` is read from the constant rather than written as "1.0.0", so this fixture keeps
# exercising the machinery after a real migration moves `STORAGE_SCHEMA_VERSION`. Pinning the
# literal would make every future bump break three tests that have nothing to do with the bump:
# `applies_to` would start returning False and the migration would refuse a release it was
# written for. `to` is a sentinel nobody will ever declare, so this cannot collide with a real
# step or be found by `migration_for`.
SYNTHETIC = Migration(
    migration_id="synthetic-add-a-column",
    from_storage_schema_version=STORAGE_SCHEMA_VERSION,
    to_storage_schema_version="9.9.9",
    description="Adds a nullable note column to the references table.",
    tables=("references",),
    transform=_add_a_column,
)

SYNTHETIC_ADDITION = Migration(
    migration_id="synthetic-add-a-table",
    from_storage_schema_version=STORAGE_SCHEMA_VERSION,
    to_storage_schema_version="9.9.9",
    description="Introduces a table the earlier version's releases never pinned.",
    added_tables=("notation_bindings",),
)


@pytest.mark.unit
@pytest.mark.requirement("DATA-56")
def test_the_declared_migrations_are_the_schema_history_and_nothing_else() -> None:
    """Inverted at W7a. It read `MIGRATIONS == {}` from W4 to W6, which was true and honest then.

    `STORAGE_SCHEMA_VERSION` had only ever been `1.0.0`, so there was no step to declare. The
    `views` table is the first real schema change, so there is now exactly one — and the
    assertion that matters is not the count but that every declared step ends where the current
    version is, so a migration cannot be declared to a version the toolkit does not produce.
    """
    assert MIGRATIONS
    targets = {step.to_storage_schema_version for step in MIGRATIONS.values()}
    assert STORAGE_SCHEMA_VERSION in targets
    assert migration_for("1.0.0", "1.1.0").added_tables == ("views",)
    with pytest.raises(MigrationError, match="no declared migration"):
        migration_for(STORAGE_SCHEMA_VERSION, "9.9.9")


@pytest.mark.unit
@pytest.mark.requirement("DATA-56")
def test_no_declared_migration_chains_through_another() -> None:
    """`migration_for` does no composition, so the registry has to be directly usable.

    With one step this is trivially true. It is asserted now because the moment a second step is
    declared, the question "can a 1.0.0 release reach 1.2.0" becomes real, and DATA-56 wants that
    answered by a declaration rather than by a runner inferring it.
    """
    starts = {step.from_storage_schema_version for step in MIGRATIONS.values()}
    ends = {step.to_storage_schema_version for step in MIGRATIONS.values()}
    assert not (starts & ends), (
        "a declared step starts where another ends; `migration_for` will not compose them, so "
        "the intermediate version needs a direct step or a reader will be stranded on it"
    )


@pytest.mark.unit
@pytest.mark.requirement("DATA-56")
def test_a_migration_cannot_both_rewrite_and_create_one_table() -> None:
    """The two lists answer different questions, so an overlap is a contradiction.

    `tables` says "this table exists and its shape changes"; `added_tables` says "this table did
    not exist". A migration claiming both about one table has no meaning `apply_migration` could
    act on, and the ambiguity would surface as whichever loop happened to run second.
    """
    with pytest.raises(MigrationError, match="both rewrites and adds"):
        Migration(
            migration_id="contradictory",
            from_storage_schema_version=STORAGE_SCHEMA_VERSION,
            to_storage_schema_version="9.9.9",
            description="Claims a table is both rewritten and new.",
            tables=("references",),
            added_tables=("references",),
        )


@pytest.mark.unit
@pytest.mark.requirement("DATA-56")
def test_a_migration_that_touches_nothing_is_refused() -> None:
    """A declared step that changes no table is a version bump pretending to be a migration."""
    with pytest.raises(MigrationError, match="no table to rewrite or add"):
        Migration(
            migration_id="empty",
            from_storage_schema_version=STORAGE_SCHEMA_VERSION,
            to_storage_schema_version="9.9.9",
            description="Declares nothing.",
        )


@pytest.mark.integration
@pytest.mark.requirement("DATA-56")
def test_a_migration_can_create_a_table_the_old_manifest_never_pinned(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """The case `apply_migration` could not express until W7a needed it.

    Every other migration path reads the old version through `manifest.table(table_id)`, which
    raises `KeyError` for an id the old manifest never carried. A table being *added* has no old
    version by definition — which is why `before` is `None` rather than a number that would look
    like a real Delta version — and no transform, because a release published before the table
    existed had no rows for it. The only honest content is the declared schema with zero rows;
    inventing rows would be fabricating architecture.
    """
    manifest = publish_release("rel-0001", example_model, expected_parent=None)
    result = apply_migration(store, SYNTHETIC_ADDITION, manifest)

    assert result.created_tables == ("notation_bindings",)
    before, after = result.versions["notation_bindings"]
    assert before is None
    assert after >= 0

    written = delta.read_version(store.table_location("notation_bindings"), version=after)
    assert written.num_rows == 0
    assert written.schema.names == list(schema_for("notation_bindings").schema.names), (
        "an added table must carry the declared schema, not an empty one"
    )


@pytest.mark.integration
@pytest.mark.requirement("DATA-56")
def test_a_migration_writes_new_versions_and_leaves_the_old_ones_readable(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """§10E: an earlier release stays queryable, including after an intentional schema migration.

    This is the property that makes retention meaningful. A migration that rewrote history would
    make every retained manifest a claim about data that no longer exists in that shape.
    """
    manifest = publish_release("rel-0001", example_model, expected_parent=None)
    before = manifest.table("references").delta_version

    result = apply_migration(store, SYNTHETIC, manifest)
    assert result.migrated_tables == ("references",)
    old, new = result.versions["references"]
    assert (old, new) == (before, before + 1)

    location = store.resolve(manifest.table("references").uri)
    migrated = delta.read_version(location, version=new)
    assert "migrated_note" in migrated.schema.names
    assert migrated.column("migrated_note").to_pylist() == ["migrated"] * migrated.num_rows

    # The pinned version still reads, with its *old* schema.
    replayed = historical_replay(store, manifest, tables=["references"])
    assert "migrated_note" not in replayed["references"].names
    # And the whole release still assembles into the model it published.
    assert model_digest(read_model(store, manifest)) == manifest.model_digest


@pytest.mark.integration
@pytest.mark.requirement("DATA-56")
def test_a_migration_refuses_a_release_at_the_wrong_schema_version(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    """No chaining and no inference: a runner that guessed would be inferring what DATA-56 wants
    stated."""
    manifest = publish_release("rel-0001", example_model, expected_parent=None)
    wrong = Migration(
        migration_id="from-2.0.0",
        from_storage_schema_version="2.0.0",
        to_storage_schema_version="2.1.0",
        description="Starts somewhere this release has never been.",
        tables=("references",),
        transform=_add_a_column,
    )
    assert not wrong.applies_to(manifest)
    with pytest.raises(MigrationError, match="starts at storage schema"):
        apply_migration(store, wrong, manifest)


@pytest.mark.integration
@pytest.mark.requirement("DATA-56")
def test_a_migration_records_what_it_was_in_the_commit(
    store: ReleaseStore, example_model: Model, publish_release: Publisher
) -> None:
    manifest = publish_release("rel-0001", example_model, expected_parent=None)
    apply_migration(store, SYNTHETIC, manifest)
    location = store.resolve(manifest.table("references").uri)
    entry = delta.history(location, version=delta.tip(location))[0]
    # Read from the declaration rather than retyped, so the fixture's version independence is not
    # undone here by three string literals.
    assert entry["migration_id"] == SYNTHETIC.migration_id
    assert entry["storage_schema_version"] == SYNTHETIC.to_storage_schema_version
    assert entry["migrated_from"] == SYNTHETIC.from_storage_schema_version
