"""The two comparison namespaces, in a module both the context and the recipes can import.

`Side` is the one name shared between how a comparison is *registered* (`queries/context.py`) and
how a recipe *declares* which release each of its inputs comes from (`queries/recipes.py`). Putting
it in either of those would make the other import it, and the two are deliberately independent:
one is a generated schema contract, the other is a DataFusion session.
"""

from typing import Final, Literal, get_args

__all__ = ["SIDES", "Side"]

Side = Literal["base", "candidate"]

SIDES: Final[tuple[Side, ...]] = get_args(Side)
"""The two sides DATA-47 names, derived from the type so the two cannot drift."""
