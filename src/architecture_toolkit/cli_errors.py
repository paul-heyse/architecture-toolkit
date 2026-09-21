"""How a command refuses, declared once (DATA-38).

Before this module the CLI refused in 35 places through `argparse.ArgumentParser.exit`, which
meant 22 handlers took a `parser` argument for no other purpose. Worse, the *meaning* of a refusal
lived at the call site: exit code 2 came to carry five unrelated things — a mistyped flag, an id
that does not exist, a library declining a well-formed request, a file that would not parse, and
`output` truthfully reporting that W8 is unimplemented. The same class of failure reached stdout in
one `except` clause and stderr in the next one of the same `try`.

So the refusal declares itself. A `CommandRefused` subclass states its exit code and its stream as
class variables, `report()` is the only thing that writes, and `cli.py` translates library
exceptions into this hierarchy in exactly one place. That makes two things checkable that were
previously conventions: `tests/unit/test_cli_errors.py` asserts every subclass declares both, and
the exit-code table can be printed, diffed and reviewed.

**Our own hierarchy rather than Click's.** Typer vendors Click under `typer._click` since 0.26.0,
`ClickException` is not re-exported on `typer`, and the public surface is `Abort`, `BadParameter`,
`Exit` and `TyperException`. Subclassing the vendored exception would be a private-API dependency
of the kind `rules/` exists to prevent, and subclassing the *installed* `click` — which mkdocs
brings in — would subclass an unrelated class that Typer's dispatcher never catches.

**Typer keeps what it is good at.** Parse-time failures — an unknown flag, a value outside an
enum, a path that does not exist — stay Typer's, and it already exits 2 for them. This hierarchy is
for refusals that need the store, the registry or the model to discover.
"""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar, Final

from rich.console import Console

__all__ = [
    "ERR_CONSOLE",
    "EXIT_DIAGNOSTICS",
    "EXIT_OK",
    "EXIT_UNREADABLE",
    "EXIT_USAGE",
    "OUT_CONSOLE",
    "CommandRefused",
    "DiagnosticsFound",
    "OperationRefused",
    "SourceUnreadable",
    "Stream",
    "UnknownName",
    "UsageRefusal",
]

# Exit codes are part of the interface. Four, and no more:
#   0  nothing at or above the failure threshold
#   1  a hard structural error
#   2  usage, or a command that is not implemented
#   3  the source could not be read or parsed, so no rule could run
# 3 exists because "that file is not YAML" and "this model has four unresolved endpoints" are
# different operational outcomes and CI wants to branch on them.
EXIT_OK: Final[int] = 0
EXIT_DIAGNOSTICS: Final[int] = 1
EXIT_USAGE: Final[int] = 2
EXIT_UNREADABLE: Final[int] = 3


OUT_CONSOLE: Final[Console] = Console(soft_wrap=True)
ERR_CONSOLE: Final[Console] = Console(stderr=True, soft_wrap=True)
"""Rich, with the one setting that makes it safe for messages somebody has to read.

Rich hard-wraps to the terminal width by default, which chops a long refusal mid-sentence and makes
the same command produce different output on a developer's terminal and on a runner — measured at
ten stderr lines under `COLUMNS=40` against five under `COLUMNS=200`. `soft_wrap=True` leaves the
line whole and lets the terminal do the wrapping, so what a pipeline greps for is what was written.

Colour needs no configuration: rich detects a non-terminal and emits no escapes, so piped output
and CI logs are plain by construction. Machine-readable output still goes through `print`, never
through a console — three tests validate CLI stdout against generated JSON Schemas and require
pure JSON with nothing else on the stream.
"""


class Stream(StrEnum):
    """Where a refusal is written.

    A property of the refusal, not of the call site. The rule the previous code broke in adjacent
    `except` clauses: a refusal an operator caused goes to stderr so a pipeline can separate it
    from output, and a *finding about the model* goes to stdout because it is the answer.
    """

    OUT = "stdout"
    ERR = "stderr"


class CommandRefused(Exception):
    """A refusal that carries how it is reported. Never raised directly — subclass it.

    Deliberately not a `RuntimeError`. `typer.Exit` and `typer.Abort` are `RuntimeError`s, so a
    broad `except RuntimeError` in a command body would swallow Typer's own control flow; keeping
    this hierarchy on `Exception` means the two can never be confused for one another.
    """

    exit_code: ClassVar[int]
    stream: ClassVar[Stream]

    def report(self) -> int:
        """Write the message where this class says it goes, and answer with its code."""
        console = ERR_CONSOLE if self.stream is Stream.ERR else OUT_CONSOLE
        console.print(self.args[0], highlight=False, markup=False)
        return self.exit_code


class UsageRefusal(CommandRefused):
    """The operator asked for something incoherent — flags that contradict, or a missing pairing.

    Distinct from Typer's own parse errors, which catch what can be known without touching the
    store. This is for what cannot: `--expect-parent` is required only when the store already has
    a current release.
    """

    exit_code = EXIT_USAGE
    stream = Stream.ERR


class UnknownName(CommandRefused):
    """A recipe, policy, release, schema family or analysis that does not exist.

    Its own class rather than a `UsageRefusal` because the two answer different questions — "you
    typed this wrong" versus "that is spelled fine and is not here" — and an operator reading a
    log wants to know which.
    """

    exit_code = EXIT_USAGE
    stream = Stream.ERR


class DiagnosticsFound(CommandRefused):
    """The model carries findings at or above the failure threshold.

    Not a refusal of the request: the command did what was asked and the answer is bad news. That
    is why it goes to stdout — it is the output.
    """

    exit_code = EXIT_DIAGNOSTICS
    stream = Stream.OUT


class OperationRefused(CommandRefused):
    """A release, archive or retention operation the library declined.

    A stale parent, an unreadable pinned version, a vacuum that would strand a retained release.
    Shares the exit code with `DiagnosticsFound` because both mean "the tool ran and the answer is
    no", and both are output rather than usage.
    """

    exit_code = EXIT_DIAGNOSTICS
    stream = Stream.OUT


class SourceUnreadable(CommandRefused):
    """The input could not be read or parsed, so no rule could run.

    The reason exit code 3 exists. Applies to every input the toolkit parses — a YAML model, a
    JSON change set, a change report — which is the inconsistency this class settles: two of those
    three used to report code 2.
    """

    exit_code = EXIT_UNREADABLE
    stream = Stream.OUT
