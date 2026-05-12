"""Cron and one-time scheduler adapters."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .config import legacy_autobuild_dir, merged_env


def _call_legacy(script_name: str, *extra: str) -> int:
    env = merged_env(None)
    script = legacy_autobuild_dir(env) / script_name
    if not script.exists():
        raise SystemExit(f"Missing legacy script: {script}")
    return subprocess.call([str(script), *extra], env=env)


def install_cron(args) -> int:
    extra = ["--dry-run"] if getattr(args, "dry_run", False) else []
    return _call_legacy("install_autobuild_cron.sh", *extra)


def _print_test_once_dry_run() -> int:
    env = merged_env(None)
    root = legacy_autobuild_dir(env)
    config_root = Path(env.get("AUTOBUILD_CONFIG_ROOT", root / "config"))
    log_root = Path(env.get("AUTOBUILD_LOG_ROOT", "/home/jamesahn/gct_workspace/autobuild/logs"))
    state_root = Path(env.get("AUTOBUILD_STATE_ROOT", "/home/jamesahn/gct_workspace/autobuild/state"))
    start_after = int(env.get("START_AFTER_MINUTES", "5"))
    notifier_start = int(env.get("NOTIFIER_START_AFTER_MINUTES", str(start_after + 10)))
    notifier_interval = int(env.get("NOTIFIER_INTERVAL_MINUTES", "10"))
    notifier_repeat = int(env.get("NOTIFIER_REPEAT_COUNT", "72"))
    test_run_ts = env.get("TEST_RUN_TS", "<YYYYMMDD_HHMMSS>")
    status_file = state_root / f"one_time_daily_autobuild_status_{test_run_ts}.txt"

    jobs = [
        (0, "GDM7275X OpenWrt v1.00", root / "openwrt_autobuild.sh", config_root / "openwrt_v1.00_autobuild.env", log_root / "openwrt/v1.00/cron_runner.log"),
        (1, "GDM7275X OpenWrt master", root / "openwrt_autobuild.sh", config_root / "openwrt_master_autobuild.env", log_root / "openwrt/master/cron_runner.log"),
        (2, "GDM7275X Linuxos master", root / "os_autobuild.sh", config_root / "gdm7275x_linuxos_master_autobuild.env", log_root / "linuxos/gdm7275x/cron_runner.log"),
        (3, "GDM7275X Zephyros", root / "zephyros_autobuild.sh", config_root / "zephyros_autobuild.env", log_root / "zephyros/cron_runner.log"),
        (4, "GDM7243A uTKernel", root / "os_autobuild.sh", config_root / "gdm7243a_utkernel_autobuild.env", log_root / "uTKernel/gdm7243a/cron_runner.log"),
        (5, "GDM7243ST uTKernel", root / "os_autobuild.sh", config_root / "gdm7243st_utkernel_autobuild.env", log_root / "uTKernel/gdm7243st/cron_runner.log"),
        (6, "GDM7243i zephyr-v2.3", root / "os_autobuild.sh", config_root / "gdm7243i_zephyr_v2.3_autobuild.env", log_root / "zephyr_v2_3/gdm7243i/cron_runner.log"),
    ]
    for offset, label, script, config, log_file in jobs:
        print(f"[SCHEDULE] +{start_after + offset} min: {label}")
        print(f"           CONFIG_FILE={config} DAILY_STATUS_FILE={status_file} {script} >> {log_file} 2>&1")

    notifier = root / "send_daily_autobuild_report.sh"
    notifier_log = log_root / "notifier/daily_autobuild_mail_notifier.log"
    for idx in range(notifier_repeat):
        offset = notifier_start + idx * notifier_interval
        print(f"[SCHEDULE] +{offset} min: Daily notifier attempt {idx + 1}/{notifier_repeat}")
        print(f"           MIN_RUN_TS={test_run_ts} DAILY_STATUS_FILE={status_file} {notifier} >> {notifier_log} 2>&1")
    return 0


def test_once(args) -> int:
    if getattr(args, "dry_run", False):
        return _print_test_once_dry_run()
    extra = ["--dry-run"] if getattr(args, "dry_run", False) else []
    return _call_legacy("run_daily_autobuild_test_once.sh", *extra)
