"""What the projection layer refuses, and why each refusal is its own type.

The split follows `queries/errors.py`: a caller catching one of these has to decide something
different in each case. A template that does not exist is a typo; a template whose context needs
something the DTO does not carry is a contract failure and means the template and the builder
disagree; a bundle that cannot be enumerated means the digest would be a claim about less than the
generator actually reads; and a schema reference that is not pinned means a validation would be
against bytes nobody reviewed.

None of these is a `Diagnostic`. Diagnostics say something about the model; these say something
about the generator.
"""

__all__ = [
    "ProjectionError",
    "TemplateBundleError",
    "TemplateContractError",
    "TemplateError",
    "UnknownTemplateError",
]


class ProjectionError(Exception):
    """Base for every failure the projection layer raises on its own account."""


class TemplateError(ProjectionError):
    """A template is not usable as declared."""


class UnknownTemplateError(TemplateError, KeyError):
    """A template name the loader cannot resolve.

    `KeyError` as well, for the same reason `UnknownRecipeError` is: the loader is a lookup and a
    caller naming a template should be able to catch what a failed lookup normally raises.
    """


class TemplateContractError(TemplateError):
    """A template needs a name its declared context does not carry (CORE-34).

    This is what makes the DTO a contract rather than a convention. `StrictUndefined` catches the
    same class of mistake at render time, on the one code path that happened to run; this catches
    it for every branch of every template before anything is rendered.
    """


class TemplateBundleError(TemplateError):
    """The transitive template bundle cannot be enumerated (CORE-36).

    A template chosen at run time — `{% include name %}` — is the case that matters: the bundle
    digest would then cover less than the generator actually reads, so a macro change could alter
    generated output without moving the digest that is supposed to detect exactly that.
    """
