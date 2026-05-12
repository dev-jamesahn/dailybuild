"""Build runner adapters.

The shell build wrappers stay callable while each target is converted to Python.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from .config import legacy_autobuild_dir, merged_env


def _q(value: str | Path) -> str:
    return shlex.quote(str(value))


def _run_legacy(script_name: str, config_file: str, dry_run: bool = False) -> int:
    config_path = Path(config_file).expanduser()
    if not config_path.is_file():
        raise SystemExit(f"Missing config file: {config_path}")

    env = merged_env(config_path, {"CONFIG_FILE": str(config_path)})
    script = legacy_autobuild_dir(env) / script_name
    if not script.exists():
        raise SystemExit(f"Missing legacy script: {script}")
    if dry_run:
        print(f"CONFIG_FILE={_q(config_path)} {_q(script)}")
        return 0
    return subprocess.call([str(script)], env=env)


def run_openwrt(args) -> int:
    return _run_legacy("openwrt_autobuild.sh", args.config, getattr(args, "dry_run", False))


def run_os(args) -> int:
    return _run_legacy("os_autobuild.sh", args.config, getattr(args, "dry_run", False))


def run_zephyros(args) -> int:
    return _run_legacy("zephyros_autobuild.sh", args.config, getattr(args, "dry_run", False))
