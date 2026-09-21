"""The publication lock: one local writer, and who it is (DATA-23).

`docs/contracts/data.md` says "Use one local writer and a publication lock", and is explicit that
"Cloud/distributed publication is a separate protocol requiring separate qualification". So this
is deliberately the simplest thing that is correct for one machine, and it does not pretend to be
more: no lease renewal, no distributed consensus, no network.

**`O_CREAT | O_EXCL` rather than `fcntl.flock`.** Both work on the two platforms CI runs, and
flock has the nicer property of releasing itself when the holder dies. It is not used because it
is POSIX-only and because a lock that vanishes on process death is indistinguishable, to the next
writer, from a lock that was never taken — whereas a leftover file with a pid in it is a fact
somebody can act on. The trade is made knowingly: a crashed publisher leaves a stale lock that a
person breaks with `break_lock`, after looking at what it says.

The lock guards the *publication protocol*, not the Delta tables. Delta has its own per-table
optimistic concurrency and will raise `CommitFailedError` on a stale handle — but that is a
per-table guarantee, and the thing being protected here is the coherence of eleven tables and a
pointer, which no storage engine in this stack knows about.
"""

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from architecture_toolkit.releases.errors import PublicationLockError

__all__ = ["LockHolder", "break_lock", "publication_lock", "read_lock"]


@dataclass(frozen=True, slots=True)
class LockHolder:
    """Who holds the lock. Written into the lock file so a stale one can be diagnosed."""

    pid: int
    acquired_at: str
    host: str

    def describe(self) -> str:
        return f"pid {self.pid} on {self.host} since {self.acquired_at}"


def read_lock(path: Path) -> LockHolder | None:
    """The current holder, or `None` if the lock is free or unreadable.

    An unreadable lock file returns `None` rather than raising: the caller is about to fail with
    `PublicationLockError` anyway, and a garbled holder should not mask that with a JSON error.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError, ValueError:
        return None
    try:
        return LockHolder(
            pid=int(payload["pid"]),
            acquired_at=str(payload["acquired_at"]),
            host=str(payload["host"]),
        )
    except KeyError, TypeError, ValueError:
        return None


def break_lock(path: Path) -> LockHolder | None:
    """Remove a lock file deliberately, returning whoever held it.

    Separate from acquisition on purpose. Automatically breaking a lock after a timeout would
    reintroduce exactly the concurrent-writer case the lock exists to prevent, in the one
    situation where nobody is watching.
    """
    holder = read_lock(path)
    path.unlink(missing_ok=True)
    return holder


@contextmanager
def publication_lock(path: Path) -> Iterator[LockHolder]:
    """Hold the publication lock for the duration of the block.

    Released in a `finally`, so an exception raised by any publication step — including the ones
    a fault-injection test raises — still frees the lock. The file is removed rather than
    truncated: an empty lock file and a free lock should not be different states.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    holder = LockHolder(
        pid=os.getpid(),
        acquired_at=datetime.now(UTC).isoformat(),
        host=os.uname().nodename if hasattr(os, "uname") else "unknown",
    )
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        existing = read_lock(path)
        held_by = existing.describe() if existing else "an unreadable lock file"
        message = f"the publication lock at {path} is held by {held_by}"
        raise PublicationLockError(message) from None
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(
                {"pid": holder.pid, "acquired_at": holder.acquired_at, "host": holder.host}, stream
            )
        yield holder
    finally:
        path.unlink(missing_ok=True)
