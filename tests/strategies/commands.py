"""Change command strategies (CORE-45, CORE-10).

Commands are drawn *against a baseline* rather than in isolation. A `RenameElement` naming an
element that does not exist is a valid command and an invalid application, and conflating the
two makes the hard-gate property untestable: it would spend most of its examples on
`CommandError` instead of on whether a rename preserves identity.
"""

from hypothesis import strategies as st

from architecture_toolkit.domain.commands import (
    AddElement,
    ChangeSet,
    RenameElement,
    RetireElement,
    UpdateElement,
)
from architecture_toolkit.domain.model import Model
from tests.strategies.domain import elements, names
from tests.strategies.ids import element_ids

__all__ = ["add_elements", "change_sets", "rename_elements", "retire_elements"]


def _existing(baseline: Model) -> st.SearchStrategy[str]:
    return st.sampled_from([element.element_id for element in baseline.elements])


def rename_elements(baseline: Model) -> st.SearchStrategy[RenameElement]:
    return st.builds(RenameElement, element_id=_existing(baseline), new_name=names)


def retire_elements(baseline: Model) -> st.SearchStrategy[RetireElement]:
    return st.builds(
        RetireElement, element_id=_existing(baseline), reason=st.none() | st.text(max_size=40)
    )


def add_elements(baseline: Model) -> st.SearchStrategy[AddElement]:
    """Only elements whose identity is free, so the command is applicable by construction."""
    taken = {element.element_id for element in baseline.elements}
    return st.builds(
        AddElement,
        element=elements(model_id=baseline.model_id).filter(
            lambda element: element.element_id not in taken
        ),
    )


def update_elements(baseline: Model) -> st.SearchStrategy[UpdateElement]:
    return st.builds(
        UpdateElement,
        element_id=_existing(baseline),
        name=st.none() | names,
        description=st.none() | st.text(max_size=60),
    )


def change_sets(baseline: Model) -> st.SearchStrategy[ChangeSet]:
    command = st.one_of(
        rename_elements(baseline), retire_elements(baseline), update_elements(baseline)
    )
    return st.builds(
        ChangeSet,
        change_set_id=element_ids,
        model_id=st.just(baseline.model_id),
        commands=st.lists(command, min_size=1, max_size=4).map(tuple),
    )
