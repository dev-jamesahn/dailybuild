"""Cron and one-time scheduler adapters."""

from __future__ import annotations

import datetime as dt
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import AutobuildPaths, merged_env


def install_cron(args) -> int:
    lines = _daily_cron_lines()
    if getattr(args, "dry_run", False):
        print("Cron entries to install:")
        for line in lines:
            print(line)
        return 0

    _validate_daily_cron_inputs()
    _install_crontab(lines)
    print("Installed cron entries:")
    for line in lines:
        print(line)
    return 0


@dataclass(frozen=True)
class ScheduledCommand:
    offset_minutes: int
    label: str
    command: str


def _q(value: str | Path) -> str:
    return shlex.quote(str(value))


def _shell_env(**values: str | Path) -> str:
    return " ".join(f"{key}={_q(value)}" for key, value in values.items() if value is not None)


CRON_TAGS = [
    "OPENWRT_V100_AUTOBUILD",
    "OPENWRT_AUTOBUILD_V100",
    "OPENWRT_AUTOBUILD_MASTER",
    "ZEPHYROS_AUTOBUILD",
    "GDM7275X_LINUXOS_MASTER_AUTOBUILD",
    "GDM7243A_UTKERNEL_AUTOBUILD",
    "GDM7243ST_UTKERNEL_AUTOBUILD",
    "GDM7243I_ZEPHYR_V2_3_AUTOBUILD",
    "DAILY_AUTOBUILD_MAIL_NOTIFIER",
]


def _daily_cron_jobs() -> list[tuple[str, str, str, str, str]]:
    return [
        ("0 0 * * *", "run-openwrt", "openwrt_v1.00_autobuild.env", "openwrt/v1.00/cron_runner.log", "# OPENWRT_AUTOBUILD_V100"),
        ("1 0 * * *", "run-openwrt", "openwrt_master_autobuild.env", "openwrt/master/cron_runner.log", "# OPENWRT_AUTOBUILD_MASTER"),
        ("2 0 * * *", "run-os", "gdm7275x_linuxos_master_autobuild.env", "linuxos/gdm7275x/cron_runner.log", "# GDM7275X_LINUXOS_MASTER_AUTOBUILD"),
        ("3 0 * * *", "run-zephyros", "zephyros_autobuild.env", "zephyros/cron_runner.log", "# ZEPHYROS_AUTOBUILD"),
        ("4 0 * * *", "run-os", "gdm7243a_utkernel_autobuild.env", "uTKernel/gdm7243a/cron_runner.log", "# GDM7243A_UTKERNEL_AUTOBUILD"),
        ("5 0 * * *", "run-os", "gdm7243st_utkernel_autobuild.env", "uTKernel/gdm7243st/cron_runner.log", "# GDM7243ST_UTKERNEL_AUTOBUILD"),
        ("6 0 * * *", "run-os", "gdm7243i_zephyr_v2.3_autobuild.env", "zephyr_v2_3/gdm7243i/cron_runner.log", "# GDM7243I_ZEPHYR_V2_3_AUTOBUILD"),
    ]


def daily_build_log_specs() -> list[tuple[str, str]]:
    return [
        ("openwrt-v1.00", "openwrt/v1.00/cron_runner.log"),
        ("openwrt-master", "openwrt/master/cron_runner.log"),
        ("linuxos-gdm7275x", "linuxos/gdm7275x/cron_runner.log"),
        ("zephyros", "zephyros/cron_runner.log"),
        ("utkernel-gdm7243a", "uTKernel/gdm7243a/cron_runner.log"),
        ("utkernel-gdm7243st", "uTKernel/gdm7243st/cron_runner.log"),
        ("zephyr-v2.3-gdm7243i", "zephyr_v2_3/gdm7243i/cron_runner.log"),
    ]


def _daily_cron_lines() -> list[str]:
    repo_root = Path(__file__).resolve().parents[1]
    config_root = _config_root(repo_root)
    env = merged_env(config_root / "autobuild_common.env")
    entrypoint = repo_root / "autobuild.py"
    log_root = AutobuildPaths.from_env(env).log_root
    lines = []
    for schedule, subcommand, config_name, log_rel, tag in _daily_cron_jobs():
        config_file = config_root / config_name
        log_file = log_root / log_rel
        line = f"{schedule} {_q(entrypoint)} {subcommand} --config {_q(config_file)} >> {_q(log_file)} 2>&1 {tag}"
        lines.append(line)
    notifier_log = log_root / "notifier/daily_autobuild_mail_notifier.log"
    common_config = config_root / "autobuild_common.env"
    lines.append(f"*/10 * * * * {_q(entrypoint)} notify --config {_q(common_config)} >> {_q(notifier_log)} 2>&1 # DAILY_AUTOBUILD_MAIL_NOTIFIER")
    return lines


def _validate_daily_cron_inputs() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    config_root = _config_root(repo_root)
    env = merged_env(config_root / "autobuild_common.env")
    required = [config_root / "autobuild_common.env"]
    required.extend(config_root / job[2] for job in _daily_cron_jobs())
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("Missing required config file(s):\n" + "\n".join(missing))

    upload_dir = merged_env(config_root / "autobuild_common.env").get("SAMBA_UPLOAD_LOCAL_DIR", "")
    if upload_dir and not os.access(upload_dir, os.W_OK):
        raise SystemExit(f"Samba upload local dir is not writable: {upload_dir}")

    log_root = AutobuildPaths.from_env(env).log_root
    for _, _, _, log_rel, _ in _daily_cron_jobs():
        (log_root / log_rel).parent.mkdir(parents=True, exist_ok=True)
    (log_root / "notifier").mkdir(parents=True, exist_ok=True)


def _install_crontab(lines: list[str]) -> None:
    current = subprocess.run(["crontab", "-l"], text=True, capture_output=True)
    existing = current.stdout.splitlines() if current.returncode == 0 else []
    kept = [line for line in existing if not any(tag in line for tag in CRON_TAGS)]
    new_cron = "\n".join(kept + lines) + "\n"
    subprocess.run(["crontab", "-"], input=new_cron, text=True, check=True)


def _test_once_plan() -> tuple[list[ScheduledCommand], Path]:
    repo_root = Path(__file__).resolve().parents[1]
    config_root = _config_root(repo_root)
    env = merged_env(config_root / "autobuild_common.env")
    paths = AutobuildPaths.from_env(env)
    entrypoint = repo_root / "autobuild.py"
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
        done_guard = f"if [ -f {_q(sent_flag)} ] && [ -f {_q(upload_flag)} ]; then exit 0; fi"
        command = f"{done_guard}; {env_prefix} {_q(entrypoint)} notify --run-date {_q(run_date)} --config {_q(config_root / 'autobuild_common.env')} --min-run-ts {_q(test_run_ts)} >> {_q(notifier_log)} 2>&1"
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


def _config_root(repo_root: Path) -> Path:
    return Path(os.environ.get("AUTOBUILD_CONFIG_ROOT", repo_root / "config")).expanduser()
