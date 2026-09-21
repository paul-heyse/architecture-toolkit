"""The deterministic Jinja environment and the template/DTO contract (CORE-32..CORE-38).

Adversarial cases use a `DictLoader` rather than files under `projections/templates/`, because
CORE-37 says the shipped template set is trusted checked-in code: a template whose whole purpose
is to be rejected does not belong in it.
"""

import pathlib

import pytest
from jinja2 import DictLoader, Environment, StrictUndefined, UndefinedError
from pydantic import BaseModel

from architecture_toolkit.domain.authoring import parse_model, parse_source
from architecture_toolkit.domain.semantics import model_digest
from architecture_toolkit.projections.errors import (
    TemplateBundleError,
    TemplateContractError,
    UnknownTemplateError,
)
from architecture_toolkit.projections.summary import ModelSummary, summary_of
from architecture_toolkit.projections.text import (
    FILTERS,
    bundle_for,
    check_template,
    environment,
    render,
)

ROOT = pathlib.Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "minimal" / "model.yaml"
SUMMARY = "model-summary.md.j2"


def loaded(sources: dict[str, str]) -> Environment:
    """An environment over literal sources, with the shipped settings and filters."""
    env = environment()
    env.loader = DictLoader(sources)
    return env


class Context(BaseModel):
    """A stand-in DTO for the adversarial cases."""

    title: str = "t"
    items: tuple[str, ...] = ()


# -- the environment ------------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("CORE-33")
def test_the_environment_pins_every_setting_that_changes_generated_bytes() -> None:
    """A default that moves between jinja2 releases would move every projection digest."""
    env = environment()
    assert env.undefined is StrictUndefined
    assert env.trim_blocks
    assert env.lstrip_blocks
    assert env.keep_trailing_newline
    assert env.newline_sequence == "\n"
    assert env.autoescape is False
    assert env.auto_reload is False


@pytest.mark.unit
@pytest.mark.requirement("CORE-33", "CORE-35")
def test_the_two_nondeterministic_builtins_are_gone() -> None:
    """Measured before they were deleted: `random` gave ten distinct results in twelve renders.

    `lipsum` and `random` are the only two members of Jinja's default namespace that are not a
    function of their arguments. An artifact whose digest is supposed to be stable cannot reach
    either, and `StrictUndefined` would not stop it: they are defined.
    """
    env = environment()
    assert "lipsum" not in env.globals
    assert "random" not in env.filters
    with pytest.raises(TemplateContractError, match="No filter named 'random'"):
        check_template(loaded({"t.j2": "{{ items|random }}"}), "t.j2", Context)
    with pytest.raises(TemplateContractError, match=r"\['lipsum'\]"):
        check_template(loaded({"t.j2": "{{ lipsum() }}"}), "t.j2", Context)


@pytest.mark.unit
@pytest.mark.requirement("CORE-35")
def test_every_registered_filter_is_a_function_of_its_arguments_alone() -> None:
    """Purity, asserted the only way a test can: the same input twice, and no ambient reads."""
    env = environment()
    for name, function in FILTERS.items():
        assert env.filters[name] is function
    assert FILTERS["md_escape"]("a_b*c") == FILTERS["md_escape"]("a_b*c") == r"a\_b\*c"
    assert FILTERS["one_line"](" a \n  b ") == "a b"


@pytest.mark.unit
@pytest.mark.requirement("CORE-33")
def test_strict_undefined_is_the_runtime_defence_behind_the_contract_check() -> None:
    """CORE-34 is the build-time check; this is what catches a branch it could not see."""
    env = loaded({"t.j2": "{{ title }}{{ missing }}"})
    with pytest.raises(UndefinedError):
        env.get_template("t.j2").render(title="t")


# -- the bundle (CORE-36) -------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("CORE-36")
def test_the_bundle_is_the_transitive_closure_and_nothing_else() -> None:
    env = loaded(
        {
            "top.j2": '{% extends "base.j2" %}{% block b %}{% include "part.j2" %}{% endblock %}',
            "base.j2": "{% block b %}{% endblock %}",
            "part.j2": '{% from "macros.j2" import q %}{{ q(title) }}',
            "macros.j2": '{% macro q(s) %}"{{ s }}"{% endmacro %}',
            "unreferenced.j2": "{{ nobody_reads_this }}",
        }
    )
    bundle = bundle_for(env, "top.j2")
    assert bundle.paths == ("base.j2", "macros.j2", "part.j2", "top.j2")
    assert "unreferenced.j2" not in bundle.paths, (
        "the bundle is what this rendering reads, not what the package ships; adding an unused "
        "template must not invalidate a released artifact"
    )
    assert bundle.digest.startswith("sha256:")


@pytest.mark.unit
@pytest.mark.requirement("CORE-36")
def test_a_macro_edit_moves_the_digest_and_traversal_order_does_not() -> None:
    """The whole point of a transitive digest: a change two files away is still a change."""
    sources = {
        "top.j2": '{% import "macros.j2" as m %}{{ m.q(title) }}',
        "macros.j2": '{% macro q(s) %}"{{ s }}"{% endmacro %}',
    }
    first = bundle_for(loaded(sources), "top.j2")
    reordered = bundle_for(loaded(dict(reversed(list(sources.items())))), "top.j2")
    assert reordered.digest == first.digest

    edited = dict(sources) | {"macros.j2": "{% macro q(s) %}{{ s }}{% endmacro %}"}
    assert bundle_for(loaded(edited), "top.j2").digest != first.digest


@pytest.mark.unit
@pytest.mark.requirement("CORE-36")
def test_a_template_chosen_at_run_time_is_refused_rather_than_skipped() -> None:
    """`find_referenced_templates` yields `None` here, and the `None` is the whole signal.

    Skipping it would leave a bundle digest covering less than the generator actually reads, so a
    macro change could alter output without moving the digest that exists to detect exactly that.
    """
    env = loaded({"t.j2": "{% include chooser %}"})
    with pytest.raises(TemplateBundleError, match="chosen at run time"):
        bundle_for(env, "t.j2")


@pytest.mark.unit
@pytest.mark.requirement("CORE-36")
def test_a_template_that_does_not_exist_is_a_lookup_failure() -> None:
    with pytest.raises(UnknownTemplateError):
        bundle_for(environment(), "no-such-template.md.j2")


# -- the contract check (CORE-34) -----------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("CORE-34")
def test_a_template_needing_a_name_the_dto_lacks_is_refused_before_anything_renders() -> None:
    env = loaded({"t.j2": "{{ title }}{% if secret %}x{% endif %}"})
    with pytest.raises(TemplateContractError, match=r"needs \['secret'\]"):
        check_template(env, "t.j2", Context)


@pytest.mark.unit
@pytest.mark.requirement("CORE-34")
def test_the_check_covers_a_branch_a_render_would_not_reach() -> None:
    """The reason a build-time check exists at all: `StrictUndefined` only sees what runs."""
    env = loaded({"t.j2": "{% if false %}{{ never_evaluated }}{% endif %}"})
    assert env.get_template("t.j2").render() == ""
    with pytest.raises(TemplateContractError, match="never_evaluated"):
        check_template(env, "t.j2", Context)


@pytest.mark.unit
@pytest.mark.requirement("CORE-34", "CORE-35")
def test_an_unregistered_test_is_refused_because_jinja_does_not_refuse_it() -> None:
    """The asymmetry that needs its own assertion.

    An unknown *filter* raises from `find_undeclared_variables`, because that call runs the real
    code generator. An unknown *test* does not — measured — so it would otherwise reach a render
    and fail there, on whichever branch happened to run.
    """
    env = loaded({"t.j2": "{% if title is weird %}x{% endif %}"})
    with pytest.raises(TemplateContractError, match=r"test\(s\) \['weird'\]"):
        check_template(env, "t.j2", Context)


@pytest.mark.unit
@pytest.mark.requirement("CORE-34")
def test_a_top_level_import_inside_an_inheriting_template_says_how_to_fix_itself() -> None:
    """The one place the library's analysis is stricter than its own compiler.

    `find_undeclared_variables` does not carry a top-level `{% import %}` binding into a block's
    frame, although the real compiler does. Rather than track Jinja's scoping rules in a bespoke
    AST walk, the convention is that the import goes inside the block — and the message says so,
    because a bare set difference would send the reader hunting for a variable named `m`.
    """
    outer = loaded(
        {
            "t.j2": '{% extends "b.j2" %}{% import "m.j2" as m %}'
            "{% block c %}{{ m.q(title) }}{% endblock %}",
            "b.j2": "{% block c %}{% endblock %}",
            "m.j2": "{% macro q(s) %}{{ s }}{% endmacro %}",
        }
    )
    with pytest.raises(TemplateContractError, match="move the"):
        check_template(outer, "t.j2", Context)

    inner = loaded(
        {
            "t.j2": '{% extends "b.j2" %}'
            '{% block c %}{% import "m.j2" as m %}{{ m.q(title) }}{% endblock %}',
            "b.j2": "{% block c %}{% endblock %}",
            "m.j2": "{% macro q(s) %}{{ s }}{% endmacro %}",
        }
    )
    assert check_template(inner, "t.j2", Context) == frozenset({"title"})


# -- the shipped template -------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.requirement("CORE-32", "CORE-34")
def test_the_shipped_template_asks_for_exactly_what_the_dto_carries() -> None:
    """Both directions. Asking for more is a contract error; asking for less is dead DTO weight."""
    used = check_template(environment(), SUMMARY, ModelSummary)
    assert used == frozenset(ModelSummary.model_fields)


@pytest.mark.unit
@pytest.mark.requirement("CORE-33", "CORE-36")
def test_the_same_dto_and_bundle_render_identical_bytes() -> None:
    model = parse_model(parse_source(EXAMPLE.read_text(), source_id="example"))
    summary = summary_of(model)
    renders = {render(environment(), SUMMARY, summary) for _ in range(3)}
    assert len(renders) == 1
    assert "sample-service" in renders.pop()


@pytest.mark.unit
@pytest.mark.requirement("CORE-32")
def test_rendering_takes_a_typed_dto_and_hands_the_template_nothing_else() -> None:
    """A `dict` context would let a caller pass whatever it had, leaving nothing to check."""
    model = parse_model(parse_source(EXAMPLE.read_text(), source_id="example"))
    output = render(environment(), SUMMARY, summary_of(model))
    assert output.startswith("# sample-service\n")
    assert "| capability-1 |" in output
    assert model_digest(model) in output, (
        "the model digest is on the artifact, so a reader can trace it back to a model"
    )
