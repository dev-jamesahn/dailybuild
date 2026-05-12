"""Small lock directory helper for cron-style commands."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


class LockHeld(RuntimeError):
    """Raised when another process owns the lock."""


class LockDir:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.pid_file = self.path / "pid"
        self.acquired = False

    def __enter__(self) -> "LockDir":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.mkdir()
        except FileExistsError:
            if self._owner_alive():
                raise LockHeld(str(self.path))
            shutil.rmtree(self.path, ignore_errors=True)
            self.path.mkdir()
        self.pid_file.write_text(f"{os.getpid()}\n", encoding="utf-8")
        self.acquired = True
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if not self.acquired:
            return
        try:
            self.pid_file.unlink(missing_ok=True)
            self.path.rmdir()
        finally:
            self.acquired = False

    def _owner_alive(self) -> bool:
        try:
            pid = int(self.pid_file.read_text(encoding="utf-8").strip())
        except (FileNotFoundError, ValueError):
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
