"""What a snapshot provider says about itself (DATA-34, DATA-11B).

`ARCH-TOOL-DATA-001` §11B requires a provider to report its own identity and the library versions
it is built on, because "the materialized fallback" and "the streaming candidate" are different
claims about correctness and a qualification record that cannot tell them apart proves nothing.

**The description is deterministic on purpose.** No timestamps, no filesystem paths, no process
identifiers: two runs of the same provider against the same lock produce byte-identical
descriptions. That is what lets W9 embed one in a qualification artifact and compare it across
runs, and what lets `tests/qualification/` record it with `record_property` without turning every
evidence file into a diff.

`native_ffi_enabled` defaults to `False` and is a claim, not a setting. `docs/toolchain.md` states
that direct native FFI is incompatible under the current lock; a provider that flips this to
`True` is asserting it qualified the native path on the exact stack, and the fault-injection gates
in M2 are what it has to survive.
"""

from enum import StrEnum

from architecture_toolkit.domain.base import CompiledRecord

__all__ = [
    "Materialization",
    "SnapshotProviderDescription",
]


class Materialization(StrEnum):
    """How much of a table a provider brings into memory to answer a read.

    §11B's "explicit materialization" clause: a caller choosing between providers is choosing a
    memory profile, and a provider that will not say which one it has cannot be chosen sensibly.
    """

    MATERIALIZED = "materialized"
    """The whole table is read into memory. The qualified fallback."""

    STREAMING = "streaming"
    """Batches are produced on demand through a single-pass reader."""

    LAZY_DATASET = "lazy_dataset"
    """A dataset is registered and the engine decides what to read."""


class SnapshotProviderDescription(CompiledRecord):
    """A provider's self-description, comparable across runs and embeddable in evidence."""

    provider_type: str
    materialization: Materialization
    preserves_typed_empties: bool
    """§11B: an empty table must keep its schema rather than collapse to nothing."""

    library_versions: tuple[tuple[str, str], ...] = ()
    """`(distribution, version)` pairs, sorted by name. A mapping would not be hashable."""

    native_ffi_enabled: bool = False
