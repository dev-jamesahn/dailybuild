"""Build runner adapters."""

from __future__ import annotations

import os
from pathlib import Path

from . import openwrt, osbuild, zephyros
from .config import AutobuildPaths
from .lock import LockDir, LockHeld
from .upload import safe_name


def _lock_dir(env: dict[str, str], config_path: Path) -> Path:
    target = config_path.stem
    lock_name = f"build_{safe_name(target)}.lock"
    return Path(env.get("BUILD_LOCK_DIR") or AutobuildPaths.from_env(env).tmp_root / lock_name)


def run_openwrt(args) -> int:
    return openwrt.run(args)


def run_os(args) -> int:
    return osbuild.run(args)


def run_zephyros(args) -> int:
    return zephyros.run(args)
