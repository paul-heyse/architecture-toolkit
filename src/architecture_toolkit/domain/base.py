"""The Pydantic model families and the configuration each one carries.

`ARCH-TOOL-CORE-001` §3A names five families with genuinely different rules. Four of them are
record bases and belong here. The fifth, `Diagnostic`, is shared across the Pydantic, cross-record,
XML, notation and qualification adapters, so it lives in `validation/` beside the rules that raise
it rather than in the domain it describes.

The distinction that carries weight is authoring versus compiled, and it is **not**
mutability. Both families are frozen. W2's round-trip editor rewrites the ruamel presentation
tree and reparses — it never mutates a domain record — so nothing in the toolkit needs a mutable
one, and freezing both closes CORE-09's "unvalidated in-place mutation" structurally rather than
by rule alone.

What actually separates them is collection shape. Authoring records are `list`-shaped because they
are the JSON- and YAML-facing family; compiled records are `tuple`- and `frozenset`-shaped because
they are published. That distinction is load-bearing under `strict=True`, in a way worth stating
plainly: supplying a Python `list` to a `tuple[...]` field fails with the error location
**collapsed to the field** — `('elements',)` — discarding every nested error beneath it. The same
payload through `model_validate_json` reports the full path,
`('elements', 0, 'detail', 'interface', 'protocol')`. So authoring input arrives as JSON, and
in-process construction of a compiled record passes real tuples. `tests/unit/test_immutability.py`
pins both halves of that.

`frozen=True` is not deep immutability, and it is worth being exact about why. Pydantic blocks
attribute assignment on the model; it does nothing about a `dict` field being mutated *through*
the frozen model, which was confirmed against the pinned version. The property that does hold
exactly is hashability: a record whose every nested field is immutable is hashable, and one
carrying a `dict`, `list` or `set` anywhere in its tree raises `TypeError: unhashable type`.
`tests/unit/test_immutability.py` applies that over every `CompiledRecord` subclass, which is why
this module does not try to police field types by naming convention.

CORE-02 sets the strict, closed baseline for all four. CORE-08 adds the freeze to the two families
where semantic immutability is the point.
"""

from pydantic import BaseModel, ConfigDict

__all__ = [
    "AuthoringRecord",
    "CommandRecord",
    "CompiledRecord",
    "ManifestRecord",
]


class AuthoringRecord(BaseModel):
    """What a person authored: strict, closed, `list`-shaped, JSON-facing.

    CORE-02. Frozen like the rest — see the module docstring for why the authoring layer does not
    need mutability. Nothing in this family is published as durable release state
    (`ARCH-TOOL-CORE-001` §3A); the compiled family is. Members are *not* hashable, because their
    collections are lists, and that is deliberate: the hashability guard is a statement about the
    compiled family only.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class CompiledRecord(BaseModel):
    """A normalized, published record: frozen, immutable nested types only.

    CORE-08. Use `tuple[...]` and `frozenset[...]`, never `list`, `set` or `dict`. Pydantic
    rejects `MappingProxyType` outright, so an immutable mapping is spelled
    `tuple[tuple[K, V], ...]`. The hashability guard enforces this for the whole subclass tree
    rather than one field at a time.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class CommandRecord(BaseModel):
    """A typed architecture mutation.

    CORE-10. Frozen because a command is a record of intent: once submitted it is history, and
    rewriting it in place would make the change set unauditable.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class ManifestRecord(BaseModel):
    """Immutable after creation (`ARCH-TOOL-CORE-001` §3A).

    Declared here in W1 and populated in W4. The base exists now so the release manifest cannot
    quietly acquire a different configuration from the records it pins.
    """

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
