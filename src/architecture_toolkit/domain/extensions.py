"""The bounded consumer extension field (DATA-13).

DATA-13 asks for "a small namespaced extension field" and the word doing the work is *small*. An
extension exists so a consumer can carry an annotation the toolkit does not model — a ticket
reference, an internal owner code — without a schema change and without a second sidecar file.

**An extension is an annotation nobody queries.** That is the rule, and it is what keeps this
field from becoming an untyped escape hatch that swallows the typed model. The moment a query
recipe, a projection or a validation rule reads an extension, it has stopped being an annotation
and become part of the model's meaning, and it graduates to a typed field through a DATA-56
migration. `tests/unit/test_extension_policy.py` enforces that direction with an AST scan over
`queries/`, `projections/` and `validation/rules/`, because a rule written in prose alone is a
rule that gets broken by the first person in a hurry.

The bounds are deliberate and they are what make the Arrow column predictable: at most sixteen
entries per record, a namespace of at least two dotted segments, a key of at most sixty-four
characters and a value of at most one kibicharacter. A record carrying a thousand extensions is
not annotated, it is a different model.
"""

from collections.abc import Iterable
from typing import Annotated, Final

from pydantic import StringConstraints

from architecture_toolkit.domain.base import CompiledRecord
from architecture_toolkit.domain.identifiers import ExtensionNamespace

__all__ = [
    "MAX_EXTENSIONS_PER_RECORD",
    "MAX_EXTENSION_KEY_LENGTH",
    "MAX_EXTENSION_VALUE_LENGTH",
    "Extension",
    "duplicate_extension_key",
]

MAX_EXTENSIONS_PER_RECORD: Final[int] = 16
"""Sixteen is a bound, not a budget. See the module docstring."""

MAX_EXTENSION_KEY_LENGTH: Final[int] = 64
MAX_EXTENSION_VALUE_LENGTH: Final[int] = 1024

_Key = StringConstraints(min_length=1, max_length=MAX_EXTENSION_KEY_LENGTH, strict=True)
_Value = StringConstraints(max_length=MAX_EXTENSION_VALUE_LENGTH, strict=True)


class Extension(CompiledRecord):
    """One namespaced annotation. The value is always a string.

    Not `object`, not a JSON blob: a typed union would be a schema the toolkit has to maintain
    for data it has promised not to interpret, and an untyped blob would not survive an explicit
    Arrow schema (DATA-10 forbids union and extension types). A consumer that needs structure
    encodes it and owns the decoding, which is the honest division.
    """

    namespace: ExtensionNamespace
    key: Annotated[str, _Key]
    value: Annotated[str, _Value]


def duplicate_extension_key(extensions: Iterable[Extension]) -> tuple[str, str] | None:
    """The first `(namespace, key)` pair that appears twice, or `None`.

    Returned rather than raised so the two callers can name the record they found it on.
    """
    seen: set[tuple[str, str]] = set()
    for extension in extensions:
        pair = (extension.namespace, extension.key)
        if pair in seen:
            return pair
        seen.add(pair)
    return None
