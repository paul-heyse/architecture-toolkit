"""The deterministic Jinja environment, and the contract between a template and its DTO.

CORE-32..CORE-38. Jinja is a bounded textual renderer for Structurizr DSL, PlantUML and generated
Markdown. It formats; it does not reason. A Python projection builder produces a fully prepared
typed DTO and this module renders it — which is why there is one factory rather than a constructor
call at each call site, and why `rules/jinja-environment-is-central.yml` says so structurally.

**Determinism is built by removal, not by hope.** Two of Jinja's own builtins are not
deterministic: the `lipsum` global generates random filler text, and the `random` filter picks one.
Both are deleted in `environment()`. Measured before deleting them — `random` produced ten distinct
outputs in twelve renders — because "no ambient random" is the kind of requirement that is easy to
declare and easy to leave unenforced. `tojson` needs no such treatment: its policy already sorts
keys.

**The contract check is three checks in one library call.** `meta.find_undeclared_variables` runs
Jinja's real code generator over the parsed template, so it reports every name the template will
look up in the context *and* raises on an unknown filter. It does not raise on an unknown test, so
`check_template` asserts those separately.

**One house rule the library forces.** `find_undeclared_variables` does not propagate a top-level
`{% import ... as m %}` binding into a `{% block %}` frame, although the real compiler does, so a
template that imports at top level and uses the alias inside a block renders correctly and is
reported as needing `m`. Rather than subtract import bindings with a bespoke AST walk — taking on
the job of tracking Jinja's scoping rules across versions — the convention is that an `{% import %}`
goes inside the block that uses it. `check_template` says so when it fires, because a contract
error whose message is a set difference would send the reader hunting for a variable named `m`.
"""

from collections.abc import Callable, Iterable, Mapping
from hashlib import sha256
from typing import Final

from jinja2 import Environment, PackageLoader, StrictUndefined, TemplateNotFound
from jinja2 import meta as jinja_meta
from jinja2 import nodes as jinja_nodes
from jinja2.exceptions import TemplateAssertionError, TemplateSyntaxError
from pydantic import BaseModel

from architecture_toolkit.domain.identifiers import Digest
from architecture_toolkit.projections.errors import (
    TemplateBundleError,
    TemplateContractError,
    UnknownTemplateError,
)

__all__ = [
    "BUNDLE_PREIMAGE",
    "FILTERS",
    "FILTER_VERSION",
    "TEMPLATE_PACKAGE",
    "TEMPLATE_ROOT",
    "TemplateBundle",
    "bundle_for",
    "check_template",
    "environment",
    "prepare",
    "render",
]

TEMPLATE_PACKAGE: Final[str] = "architecture_toolkit.projections"
TEMPLATE_ROOT: Final[str] = "templates"
"""Where baseline templates live. CORE-37: trusted, checked-in toolkit code.

A `PackageLoader` rather than a `FileSystemLoader` rooted at the working directory, so the template
set is the one that shipped with the installed toolkit and cannot be shadowed by a file a consumer
happens to have. Supporting a consumer-supplied template needs the separate sandbox and resource
model CORE-37 defers; `jinja2.sandbox.SandboxedEnvironment` is where that design would start.
"""

FILTER_VERSION: Final[str] = "1"
"""Bumped when any filter below changes what it produces.

Part of the generator identity a `ProjectionArtifact` records (CORE-36), because a filter is as
capable of changing generated output as a macro is, and a bundle digest over template *source*
cannot see it.
"""

_GLOBAL_NAMES: Final[frozenset[str]] = frozenset({"cycler", "dict", "joiner", "namespace", "range"})
"""Jinja's own globals, minus the one `environment()` removes.

Written out rather than read from `env.globals`, because a template may legitimately use any of
these and the contract check has to allow them — but reading the live mapping would also allow
anything a future factory happened to add, which is the opposite of a contract. `lipsum` is absent
for the reason `environment()` deletes it.
"""

BUNDLE_PREIMAGE: Final[str] = "architecture-toolkit/template-bundle/v1\n"
"""Prefixed like every other digest in this toolkit, so two digest kinds cannot collide."""


def md_escape(value: str) -> str:
    """Escape the Markdown metacharacters that would otherwise restructure a document.

    Deliberately not a general escaper: only the characters that change block or inline structure
    when they appear in generated prose. `_` is included because identifiers contain it and
    `sample_service` should not render as italics.
    """
    for character in ("\\", "`", "*", "_", "[", "]", "<", ">", "|", "#"):
        value = value.replace(character, "\\" + character)
    return value


def one_line(value: str) -> str:
    """Collapse whitespace so a multi-line description cannot break a table row."""
    return " ".join(value.split())


def sorted_by(records: Iterable[BaseModel], key: str) -> tuple[BaseModel, ...]:
    """Order records by one field, so presentation order is a decision rather than an accident.

    Business semantics stay in Python (CORE-35): this sorts what it is given, it does not select.
    """
    return tuple(sorted(records, key=lambda record: str(getattr(record, key))))


FILTERS: Final[Mapping[str, Callable[..., object]]] = {
    "md_escape": md_escape,
    "one_line": one_line,
    "sorted_by": sorted_by,
}
"""Pure deterministic presentation helpers, and nothing else (CORE-35).

Each is a function of its arguments alone: no clock, no environment, no filesystem, no network,
and no access to anything the DTO did not carry.
"""


def environment() -> Environment:
    """The one Jinja environment (CORE-33).

    Every setting that affects output is explicit, because a default that changes between jinja2
    releases would change generated bytes and therefore every projection digest.
    """
    env = Environment(
        loader=PackageLoader(TEMPLATE_PACKAGE, TEMPLATE_ROOT),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        newline_sequence="\n",
        # S701 is about HTML injection, and nothing this environment renders is HTML. Markdown,
        # Structurizr DSL and PlantUML are not markup; escaping `<`, `>` and `&` would corrupt
        # every one of them. The one format where escaping is load-bearing is standards XML, and
        # CORE-38 forbids Jinja from generating that at all — `projections/xml.py` builds it with
        # lxml, which escapes structurally. Templates that need Markdown escaping ask for it
        # explicitly through the `md_escape` filter, where the character set is a decision.
        autoescape=False,  # noqa: S701
        auto_reload=False,
    )
    # CORE-33: no ambient random. `lipsum` generates random filler and `random` picks a random
    # member; neither has a place in an artifact whose digest is supposed to be stable.
    env.globals.pop("lipsum", None)
    env.filters.pop("random", None)
    # pyrefly: ignore[bad-argument-type]
    # jinja2 declares `FILTERS` as a bare dict literal, so a checker infers the precise union of
    # its ~54 builtin signatures rather than the `Callable[..., Any]` the API documents. Adding a
    # filter — the supported extension point — is therefore unassignable. The narrowest possible
    # suppression on the one line that needs it (CORE-60), and `FILTERS` above is typed precisely
    # so this module's own side of the contract still checks.
    env.filters.update(FILTERS)
    return env


class TemplateBundle(BaseModel, frozen=True, strict=True, extra="forbid"):
    """Every template that can change one rendering, and a digest over all of them (CORE-36).

    `paths` is the transitive closure, sorted, so the digest does not depend on traversal order.
    A template nobody references is not in it: the bundle is what this rendering reads, not what
    the package ships, so adding an unused template must not invalidate a released artifact.
    """

    top: str
    paths: tuple[str, ...]
    digest: Digest
    filter_version: str

    @property
    def is_single_file(self) -> bool:
        return self.paths == (self.top,)


def _source_of(env: Environment, name: str) -> str:
    loader = env.loader
    if loader is None:  # pragma: no cover - `environment()` always sets one
        message = "the environment has no loader, so no template can be read"
        raise TemplateBundleError(message)
    try:
        source, _filename, _uptodate = loader.get_source(env, name)
    except TemplateNotFound as missing:
        raise UnknownTemplateError(str(missing)) from missing
    return source


def _walk(env: Environment, top: str) -> tuple[dict[str, str], set[str], set[str]]:
    """Breadth-first over the reference graph, collecting sources, names and tests used."""
    sources: dict[str, str] = {}
    undeclared: set[str] = set()
    tests: set[str] = set()
    queue = [top]
    while queue:
        name = queue.pop()
        if name in sources:
            continue
        source = _source_of(env, name)
        sources[name] = source
        try:
            parsed = env.parse(source, name=name)
        except TemplateSyntaxError as broken:
            raise TemplateBundleError(f"{name}: {broken.message}") from broken
        try:
            undeclared |= jinja_meta.find_undeclared_variables(parsed)
        except TemplateAssertionError as unknown:
            # Raised for a filter the environment does not register. `find_undeclared_variables`
            # runs Jinja's real code generator, so this check comes free with the name analysis —
            # and it is the reason CORE-35's filter registry cannot drift from the templates.
            raise TemplateContractError(f"{name}: {unknown.message}") from unknown
        tests |= {node.name for node in parsed.find_all(jinja_nodes.Test) if node.name}
        for referenced in jinja_meta.find_referenced_templates(parsed):
            if referenced is None:
                message = (
                    f"{name} references a template chosen at run time, so the bundle digest "
                    f"would cover less than the generator reads. Name the template literally."
                )
                raise TemplateBundleError(message)
            queue.append(referenced)
    return sources, undeclared, tests


def bundle_for(env: Environment, top: str) -> TemplateBundle:
    """The transitive bundle behind one template, and its digest (CORE-36).

    `meta.find_referenced_templates` supplies each edge — `{% extends %}`, `{% include %}`,
    `{% import %}` and `{% from %}` — and this walks them. It is typed as yielding `str | None`,
    and the `None` is the library reporting that a reference is computed rather than literal,
    which is refused rather than skipped.
    """
    sources, _undeclared, _tests = _walk(env, top)
    return _bundle(top, sources)


def _bundle(top: str, sources: Mapping[str, str]) -> TemplateBundle:
    payload = "".join(f"{name}\n{sources[name]}\n" for name in sorted(sources))
    digest = sha256((BUNDLE_PREIMAGE + payload).encode("utf-8")).hexdigest()
    return TemplateBundle(
        top=top,
        paths=tuple(sorted(sources)),
        digest=f"sha256:{digest}",
        filter_version=FILTER_VERSION,
    )


def check_template(env: Environment, top: str, context: type[BaseModel]) -> frozenset[str]:
    """Refuse a template that needs a name its DTO does not carry (CORE-34).

    Returns the names the bundle actually uses, so a caller can assert a template *reads* the
    fields it was given rather than only that it asks for nothing extra. `prepare` is what a
    generator calls; this is the same check when the bundle digest is not wanted.
    """
    _sources, undeclared, tests = _walk(env, top)
    _refuse_unknown_tests(env, top, tests)
    _refuse_unmet_context(top, undeclared, context)
    return frozenset(undeclared)


def _refuse_unknown_tests(env: Environment, top: str, tests: set[str]) -> None:
    unknown = sorted(tests - set(env.tests))
    if unknown:
        message = (
            f"{top} uses test(s) {unknown} that the environment does not register. "
            f"Unlike an unknown filter, Jinja does not refuse this on its own."
        )
        raise TemplateContractError(message)


def _refuse_unmet_context(top: str, undeclared: set[str], context: type[BaseModel]) -> None:
    allowed = set(context.model_fields) | set(_GLOBAL_NAMES)
    missing = sorted(undeclared - allowed)
    if missing:
        message = (
            f"{top} needs {missing}, which {context.__name__} does not carry. "
            f"If one of these is an import alias, move the `{{% import %}}` inside the block that "
            f"uses it: a top-level import is not visible to a block's frame during this analysis."
        )
        raise TemplateContractError(message)


def prepare(env: Environment, top: str, context: type[BaseModel]) -> TemplateBundle:
    """Check the contract and compute the bundle digest in one walk (CORE-34, CORE-36).

    What a generator actually needs, and the reason it is one call. `bundle_for` and
    `check_template` each walked the reference graph independently, so producing one artifact
    parsed every template in the bundle twice and read it three times. That is a constant for one
    Markdown summary and O(views x bundle) for W7b, which renders per view.

    It is also what lets `render` stop checking. `StrictUndefined` is the runtime defence — this
    module's own header says so — and the contract check is a build-time question about a
    (template, DTO) pair, not a per-render one. A caller that renders without preparing gets the
    runtime defence and no build-time one; `tests/unit/test_templates.py` asserts every shipped
    template is prepared against its DTO, which is what keeps that from being a loophole.
    """
    sources, undeclared, tests = _walk(env, top)
    _refuse_unknown_tests(env, top, tests)
    _refuse_unmet_context(top, undeclared, context)
    return _bundle(top, sources)


def render(env: Environment, top: str, context: BaseModel) -> str:
    """Render one prepared DTO through one template (CORE-32).

    The context is a Pydantic model, never a `dict`: a mapping would let a caller pass whatever it
    happened to have, and there would be nothing for `prepare` to check against.
    """
    try:
        template = env.get_template(top)
    except TemplateNotFound as missing:
        raise UnknownTemplateError(str(missing)) from missing
    return template.render({name: getattr(context, name) for name in type(context).model_fields})
