"""Cron and one-time scheduler adapters."""

from __future__ import annotations

import datetime as dt
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import AutobuildPaths, legacy_autobuild_dir, merged_env


def _call_legacy(script_name: str, *extra: str) -> int:
    env = merged_env(None)
    script = legacy_autobuild_dir(env) / script_name
    if not script.exists():
        raise SystemExit(f"Missing legacy script: {script}")
    return subprocess.call([str(script), *extra], env=env)


def install_cron(args) -> int:
    extra = ["--dry-run"] if getattr(args, "dry_run", False) else []
    return _call_legacy("install_autobuild_cron.sh", *extra)


@dataclass(frozen=True)
class ScheduledCommand:
    offset_minutes: int
    label: str
    command: str


def _q(value: str | Path) -> str:
    return shlex.quote(str(value))


def _shell_env(**values: str | Path) -> str:
    return " ".join(f"{key}={_q(value)}" for key, value in values.items() if value is not None)


def _test_once_plan() -> tuple[list[ScheduledCommand], Path]:
    env = merged_env(None)
    paths = AutobuildPaths.from_env(env)
    repo_root = Path(__file__).resolve().parents[1]
    entrypoint = repo_root / "autobuild.py"
    config_root = Path(env.get("AUTOBUILD_CONFIG_ROOT", repo_root / "config"))
    log_root = paths.log_root
    state_root = paths.state_root
    start_after = int(env.get("START_AFTER_MINUTES", "5"))
    notifier_start = int(env.get("NOTIFIER_START_AFTER_MINUTES", str(start_after + 10)))
    notifier_interval = int(env.get("NOTIFIER_INTERVAL_MINUTES", "10"))
    notifier_repeat = int(env.get("NOTIFIER_REPEAT_COUNT", "72"))
    test_run_ts = env.get("TEST_RUN_TS", dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
    run_date = env.get("RUN_DATE", test_run_ts.split("_", 1)[0])
    subject_prefix = env.get("TEST_REPORT_SUBJECT_PREFIX", "[TestPy]")
    mail_to = env.get("TEST_MAIL_TO", "jamesahn@gctsemi.com")
    status_file = state_root / f"one_time_daily_autobuild_status_{test_run_ts}.txt"
    sent_flag = state_root / f".one_time_daily_autobuild_mail_sent_{test_run_ts}.flag"
    upload_flag = state_root / f".one_time_daily_autobuild_logs_uploaded_{test_run_ts}.flag"

    build_jobs = [
        (0, "GDM7275X OpenWrt v1.00", "run-openwrt", config_root / "openwrt_v1.00_autobuild.env", log_root / "openwrt/v1.00/cron_runner.log"),
        (1, "GDM7275X OpenWrt master", "run-openwrt", config_root / "openwrt_master_autobuild.env", log_root / "openwrt/master/cron_runner.log"),
        (2, "GDM7275X Linuxos master", "run-os", config_root / "gdm7275x_linuxos_master_autobuild.env", log_root / "linuxos/gdm7275x/cron_runner.log"),
        (3, "GDM7275X Zephyros", "run-zephyros", config_root / "zephyros_autobuild.env", log_root / "zephyros/cron_runner.log"),
        (4, "GDM7243A uTKernel", "run-os", config_root / "gdm7243a_utkernel_autobuild.env", log_root / "uTKernel/gdm7243a/cron_runner.log"),
        (5, "GDM7243ST uTKernel", "run-os", config_root / "gdm7243st_utkernel_autobuild.env", log_root / "uTKernel/gdm7243st/cron_runner.log"),
        (6, "GDM7243i zephyr-v2.3", "run-os", config_root / "gdm7243i_zephyr_v2.3_autobuild.env", log_root / "zephyr_v2_3/gdm7243i/cron_runner.log"),
    ]
    state_root.mkdir(parents=True, exist_ok=True)
    commands: list[ScheduledCommand] = []
    for offset, label, subcommand, config, log_file in build_jobs:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        env_prefix = _shell_env(DAILY_STATUS_FILE=status_file)
        command = f"{env_prefix} {_q(entrypoint)} {subcommand} --config {_q(config)} >> {_q(log_file)} 2>&1"
        commands.append(ScheduledCommand(start_after + offset, label, command))

    notifier_log = log_root / "notifier/daily_autobuild_mail_notifier.log"
    notifier_log.parent.mkdir(parents=True, exist_ok=True)
    for idx in range(notifier_repeat):
        offset = notifier_start + idx * notifier_interval
        env_prefix = _shell_env(
            RUN_DATE=run_date,
            MIN_RUN_TS=test_run_ts,
            DAILY_STATUS_FILE=status_file,
            MAIL_TO=mail_to,
            REPORT_SUBJECT_PREFIX=subject_prefix,
            SENT_FLAG_FILE=sent_flag,
            UPLOAD_FLAG_FILE=upload_flag,
        )
        command = f"{env_prefix} {_q(entrypoint)} notify --run-date {_q(run_date)} --config {_q(config_root / 'autobuild_common.env')} --min-run-ts {_q(test_run_ts)} >> {_q(notifier_log)} 2>&1"
        commands.append(ScheduledCommand(offset, f"Daily notifier attempt {idx + 1}/{notifier_repeat}", command))
    return commands, log_root / "notifier/one_time_daily_test_scheduler.log"


def _schedule(commands: list[ScheduledCommand], scheduler_log: Path, dry_run: bool) -> int:
    scheduler = os.environ.get("SCHEDULER", "auto")
    if scheduler == "auto":
        scheduler = "at" if shutil.which("at") else "nohup"
    if scheduler not in {"at", "nohup"}:
        raise SystemExit(f"Invalid SCHEDULER={scheduler}. Use auto, at, or nohup.")

    scheduler_log.parent.mkdir(parents=True, exist_ok=True)
    for item in commands:
        print(f"[SCHEDULE] +{item.offset_minutes} min: {item.label}")
        print(f"           {item.command}")
        if dry_run:
            continue
        if scheduler == "at":
            subprocess.run(["at", f"now + {item.offset_minutes} minutes"], input=item.command + "\n", text=True, check=True)
        else:
            with scheduler_log.open("a", encoding="utf-8") as fp:
                subprocess.Popen(
                    ["nohup", "/bin/bash", "-lc", f"sleep {item.offset_minutes}m; {item.command}"],
                    stdout=fp,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
                fp.write(f"[INFO] nohup scheduler label={item.label} offset={item.offset_minutes}m\n")
    if not dry_run:
        print(f"[INFO] One-time daily test scheduled with {scheduler}")
    return 0


def test_once(args) -> int:
    commands, scheduler_log = _test_once_plan()
    return _schedule(commands, scheduler_log, getattr(args, "dry_run", False))
