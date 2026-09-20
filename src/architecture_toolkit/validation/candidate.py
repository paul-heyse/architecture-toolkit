"""The thing cross-record validation runs over.

core.md's flow ends at an "immutable candidate". A candidate is a model *plus the profile it is
judged against*: whether `role-1 --supports--> process-1` is legal is not a property of the model
alone, and pretending otherwise is how a registry ends up unused.

The profile is not folded into `ValidationContext`, which `ARCH-TOOL-CORE-001` §3G fixes at four
fields carrying a profile *version* rather than a profile. The version says which vocabulary was
intended; the candidate carries the vocabulary itself.
"""

from architecture_toolkit.domain.base import CompiledRecord
from architecture_toolkit.domain.model import Model
from architecture_toolkit.domain.registry import Profile

__all__ = ["Candidate"]


class Candidate(CompiledRecord):
    model: Model
    profile: Profile
