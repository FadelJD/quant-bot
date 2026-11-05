"""A lock file that prevents two instances on the same config."""

from __future__ import annotations

import os
from pathlib import Path

from kestrel.errors import ConfigError


class InstanceLock:
    """Create ``<path>`` exclusively with our pid; stale locks (dead pid) are reclaimed."""

    def __init__(self, path: Path) -> None:
        """Bind to ``path`` without acquiring."""
        self.path = Path(path)
        self._held = False

    @staticmethod
    def _alive(pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        return True

    def acquire(self) -> None:
        """Acquire or raise :class:`ConfigError` naming the holder's pid."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                other = int(self.path.read_text(encoding="utf-8").strip() or "0")
            except ValueError:
                other = 0
            if other and self._alive(other) and other != os.getpid():
                raise ConfigError(f"another kestrel instance (pid {other}) holds {self.path}") from None
            self.path.unlink(missing_ok=True)
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(str(os.getpid()))
        self._held = True

    def release(self) -> None:
        """Remove the lock if we hold it."""
        if self._held:
            self.path.unlink(missing_ok=True)
            self._held = False

    def __enter__(self) -> InstanceLock:
        """Acquire."""
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        """Release."""
        self.release()
