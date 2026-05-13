"""Follow multiple autobuild logs with stable target prefixes."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from .config import AutobuildPaths, merged_env
from .scheduler import daily_build_log_specs


@dataclass
class FollowState:
    label: str
    path: Path
    position: int = 0
    missing_reported: bool = False


def tail_logs(args) -> int:
    env = merged_env(getattr(args, "config", None))
    log_root = AutobuildPaths.from_env(env).log_root
    states = [
        FollowState(label=label, path=log_root / log_rel)
        for label, log_rel in daily_build_log_specs()
    ]
    lines = max(0, int(getattr(args, "lines", 20)))
    interval = max(0.2, float(getattr(args, "interval", 1.0)))
    follow = not getattr(args, "no_follow", False)

    for state in states:
        _print_initial_tail(state, lines)

    if not follow:
        return 0

    print("[tail-logs] following logs. Press Ctrl-C to stop.", flush=True)
    try:
        while True:
            for state in states:
                _print_new_data(state)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[tail-logs] stopped.", flush=True)
        return 0


def _print_initial_tail(state: FollowState, line_count: int) -> None:
    if not state.path.exists():
        _print_prefixed(state.label, f"[waiting] {state.path}")
        state.missing_reported = True
        return

    data = state.path.read_bytes()
    state.position = len(data)
    if line_count == 0:
        return
    text = _last_lines(data, line_count)
    for line in _split_log_lines(text):
        _print_prefixed(state.label, line)


def _print_new_data(state: FollowState) -> None:
    if not state.path.exists():
        if not state.missing_reported:
            _print_prefixed(state.label, f"[waiting] {state.path}")
            state.missing_reported = True
        return

    size = state.path.stat().st_size
    if size < state.position:
        _print_prefixed(state.label, "[rotated/truncated]")
        state.position = 0
    if size == state.position:
        return

    with state.path.open("rb") as fp:
        fp.seek(state.position)
        data = fp.read()
        state.position = fp.tell()

    if state.missing_reported:
        _print_prefixed(state.label, f"[created] {state.path}")
        state.missing_reported = False
    for line in _split_log_lines(data.decode("utf-8", errors="replace")):
        _print_prefixed(state.label, line)


def _last_lines(data: bytes, line_count: int) -> str:
    lines = data.splitlines()[-line_count:]
    return b"\n".join(lines).decode("utf-8", errors="replace")


def _split_log_lines(text: str) -> list[str]:
    lines: list[str] = []
    for chunk in text.replace("\r", "\n").splitlines():
        line = chunk.rstrip()
        if line:
            lines.append(line)
    return lines


def _print_prefixed(label: str, line: str) -> None:
    print(f"[{label}] {line}", flush=True)
