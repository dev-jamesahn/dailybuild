"""Helpers for collecting git commit metadata."""

from __future__ import annotations

import subprocess
from pathlib import Path


def last_commit(repo_dir: str | Path) -> dict[str, str]:
    fmt = "%H%n%an <%ae>%n%ad%n%s"
    proc = subprocess.run(
        ["git", "-C", str(repo_dir), "log", "-1", f"--pretty=format:{fmt}", "--date=iso-strict"],
        check=True,
        text=True,
        capture_output=True,
    )
    commit, author, date, subject = (proc.stdout.splitlines() + ["", "", "", ""])[:4]
    return {"commit": commit, "author": author, "date": date, "subject": subject}
