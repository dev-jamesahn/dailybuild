"""Build runner adapters.

The shell build wrappers stay callable while each target is converted to Python.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

from . import openwrt
from .config import AutobuildPaths, legacy_autobuild_dir, merged_env
from .lock import LockDir, LockHeld
from .upload import safe_name


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
    lock_dir = _lock_dir(env, config_path)
    subprocess_env = dict(os.environ)
    subprocess_env["CONFIG_FILE"] = str(config_path)
    if dry_run:
        print(f"LOCK_DIR={_q(lock_dir)}")
        print(f"CONFIG_FILE={_q(config_path)} /bin/bash -lc {_q(str(script))}")
        return 0
    try:
        with LockDir(lock_dir):
            return subprocess.call(["/bin/bash", "-lc", str(script)], env=subprocess_env)
    except LockHeld:
        print(f"[INFO] Build skipped: another run is in progress for {config_path}")
        return 0


def _lock_dir(env: dict[str, str], config_path: Path) -> Path:
    target = config_path.stem
    lock_name = f"build_{safe_name(target)}.lock"
    return Path(env.get("BUILD_LOCK_DIR") or AutobuildPaths.from_env(env).tmp_root / lock_name)


def run_openwrt(args) -> int:
    return openwrt.run(args)


def run_os(args) -> int:
    return _run_legacy("os_autobuild.sh", args.config, getattr(args, "dry_run", False))


def run_zephyros(args) -> int:
    return _run_legacy("zephyros_autobuild.sh", args.config, getattr(args, "dry_run", False))
