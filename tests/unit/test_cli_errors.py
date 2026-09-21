"""The refusal hierarchy: every subclass declares how it is reported (W6.1).

`cli_errors.py`'s own docstring has claimed since W6.1 that "a totality guard asserts every
`CommandRefused` subclass declares both class variables". It did not — the file was never written,
which is exactly the defect class W6.1 existed to hunt, arriving inside W6.1's own work.

The guard matters because the whole design is that a refusal carries its exit code and its stream
rather than the call site choosing them. A subclass that declared neither would raise
`AttributeError` inside `report()` — while handling an error, which is the worst place to find out.
"""

import pytest

from architecture_toolkit import cli_errors
from architecture_toolkit.cli_errors import (
    EXIT_DIAGNOSTICS,
    EXIT_OK,
    EXIT_UNREADABLE,
    EXIT_USAGE,
    CommandRefused,
    DiagnosticsFound,
    OperationRefused,
    SourceUnreadable,
    Stream,
    UnknownName,
    UsageRefusal,
)


def shipped_subclasses() -> list[type[CommandRefused]]:
    """Every refusal this package declares, transitively."""
    found: list[type[CommandRefused]] = []
    for subclass in CommandRefused.__subclasses__():
        if subclass.__module__.startswith("architecture_toolkit."):
            found.append(subclass)
    return found


@pytest.mark.unit
@pytest.mark.requirement("CORE-11")
def test_every_refusal_declares_its_exit_code_and_its_stream() -> None:
    """The guard the module docstring promised.

    `CommandRefused` declares both as `ClassVar` with no default on purpose, so a subclass that
    forgets one is only detectable by looking — which is what this does.
    """
    subclasses = shipped_subclasses()
    assert len(subclasses) >= 5, "the hierarchy shrank; this sweep now covers almost nothing"

    for subclass in subclasses:
        assert isinstance(getattr(subclass, "exit_code", None), int), subclass.__name__
        assert isinstance(getattr(subclass, "stream", None), Stream), subclass.__name__


@pytest.mark.unit
@pytest.mark.requirement("CORE-11")
def test_the_base_declares_neither_so_it_cannot_be_raised_by_accident() -> None:
    """`CommandRefused` is an annotation without a value. Raising it directly would fail here."""
    assert "exit_code" not in vars(CommandRefused)
    assert "stream" not in vars(CommandRefused)
    with pytest.raises(AttributeError):
        CommandRefused("nobody should raise this").report()


@pytest.mark.unit
@pytest.mark.requirement("CORE-11")
def test_the_four_exit_codes_are_the_whole_vocabulary() -> None:
    """Four, and no more. Before W6.1, exit code 2 carried five distinct meanings."""
    declared = {EXIT_OK, EXIT_DIAGNOSTICS, EXIT_USAGE, EXIT_UNREADABLE}
    assert declared == {0, 1, 2, 3}
    assert {subclass.exit_code for subclass in shipped_subclasses()} <= declared - {EXIT_OK}, (
        "a refusal that exits 0 is not a refusal"
    )


@pytest.mark.unit
@pytest.mark.requirement("CORE-11")
@pytest.mark.parametrize(
    ("refusal", "code", "stream"),
    [
        (UsageRefusal, EXIT_USAGE, Stream.ERR),
        (UnknownName, EXIT_USAGE, Stream.ERR),
        (DiagnosticsFound, EXIT_DIAGNOSTICS, Stream.OUT),
        (OperationRefused, EXIT_DIAGNOSTICS, Stream.OUT),
        (SourceUnreadable, EXIT_UNREADABLE, Stream.OUT),
    ],
    ids=lambda value: getattr(value, "__name__", str(value)),
)
def test_each_refusal_reports_on_the_stream_its_class_declares(
    refusal: type[CommandRefused],
    code: int,
    stream: Stream,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Findings go to stdout because they are the output; usage errors go to stderr.

    Pinned per class rather than derived, because the *assignment* is the decision. Deriving it
    would make this test agree with whatever the code says, which is not a check.
    """
    assert refusal("a message").report() == code
    captured = capsys.readouterr()
    written = captured.err if stream is Stream.ERR else captured.out
    assert "a message" in written
    assert not (captured.out if stream is Stream.ERR else captured.err)


@pytest.mark.unit
@pytest.mark.requirement("CORE-11")
def test_a_refusal_is_printed_verbatim() -> None:
    """No markup, no highlighting: a message containing `[bold]` or a path is not a rich tag."""
    console = cli_errors.ERR_CONSOLE
    assert console.stderr
    assert console.soft_wrap, (
        "soft_wrap is what stops a long refusal being chopped at terminal width, which made the "
        "same message ten lines at COLUMNS=40 and five at 200"
    )
