"""Build runner adapters.

The shell build wrappers stay callable while each target is converted to Python.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .config import legacy_autobuild_dir, merged_env


def _run_legacy(script_name: str, config_file: str) -> int:
    env = merged_env(config_file, {"CONFIG_FILE": config_file})
    script = legacy_autobuild_dir(env) / script_name
    if not script.exists():
        raise SystemExit(f"Missing legacy script: {script}")
    return subprocess.call([str(script)], env=env)


def run_openwrt(args) -> int:
    return _run_legacy("openwrt_autobuild.sh", args.config)


def run_os(args) -> int:
    return _run_legacy("os_autobuild.sh", args.config)


def run_zephyros(args) -> int:
    return _run_legacy("zephyros_autobuild.sh", args.config)
