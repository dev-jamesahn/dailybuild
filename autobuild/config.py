"""Environment-style config loading and shared path helpers."""

from __future__ import annotations

import datetime as dt
import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path


def today() -> str:
    return dt.datetime.now().strftime("%Y%m%d")


def load_env_file(path: str | Path | None, _seen: set[Path] | None = None) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path:
        return values

    env_path = Path(path).expanduser()
    if not env_path.exists():
        return values

    env_path = env_path.resolve()
    _seen = _seen or set()
    if env_path in _seen:
        return values
    _seen.add(env_path)

    include_pattern = re.compile(r'^\.\s+"\$CONFIG_DIR/([^"]+)"')
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            include = include_pattern.match(line)
            if include:
                values.update(load_env_file(env_path.parent / include.group(1), _seen))
            continue
        include = include_pattern.match(line)
        if include:
            values.update(load_env_file(env_path.parent / include.group(1), _seen))
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if "$(" in value or "${BASH_SOURCE" in value:
            continue
        try:
            values[key] = shlex.split(value, comments=False, posix=True)[0]
        except (IndexError, ValueError):
            values[key] = value.strip("'\"")
    return values


def merged_env(config_file: str | Path | None = None, overrides: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    config_values = load_env_file(config_file)
    common_config = config_values.get("AUTOBUILD_COMMON_CONFIG")
    if common_config:
        common_path = Path(common_config).expanduser()
        if not common_path.is_absolute() and config_file:
            common_path = Path(config_file).expanduser().parent / common_path
        env.update(load_env_file(common_path))
    env.update(config_values)
    if overrides:
        env.update({k: v for k, v in overrides.items() if v is not None})
    return env


@dataclass(frozen=True)
class AutobuildPaths:
    repo_root: Path
    work_root: Path
    autobuild_root: Path
    log_root: Path
    tmp_root: Path
    state_root: Path

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "AutobuildPaths":
        env = env or os.environ
        home = Path(env.get("HOME", str(Path.home()))).expanduser()
        repo_root = Path(__file__).resolve().parents[1]
        work_root = Path(env.get("GCT_WORK_ROOT") or env.get("WORK_ROOT") or home / "gct_workspace").expanduser()
        autobuild_root = Path(env.get("AUTOBUILD_ROOT") or work_root / "autobuild").expanduser()
        log_root = Path(env.get("AUTOBUILD_LOG_ROOT") or autobuild_root / "logs").expanduser()
        tmp_root = Path(env.get("AUTOBUILD_TMP_ROOT") or autobuild_root / "tmp").expanduser()
        state_root = Path(env.get("AUTOBUILD_STATE_ROOT") or autobuild_root / "state").expanduser()
        return cls(repo_root, work_root, autobuild_root, log_root, tmp_root, state_root)


def daily_status_file(env: dict[str, str], run_date: str) -> Path:
    paths = AutobuildPaths.from_env(env)
    return Path(env.get("DAILY_STATUS_FILE") or paths.state_root / f"daily_autobuild_status_{run_date}.txt")


def legacy_autobuild_dir(env: dict[str, str] | None = None) -> Path:
    env = env or os.environ
    return Path(env.get("LEGACY_AUTOBUILD_DIR", "/home/jamesahn/gct-build-tools/autobuild")).expanduser()
