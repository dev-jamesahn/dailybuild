"""Cron and one-time scheduler adapters."""

from __future__ import annotations

import datetime as dt
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import DailybuildPaths, merged_env


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


def _expiry_guard(deadline_epoch: int, test_run_ts: str) -> str:
    return f"if [ $(date +%s) -gt {deadline_epoch} ]; then echo '[INFO] One-time daily test expired: {test_run_ts}'; exit 0; fi"


CRON_TAGS = [
    "OPENWRT_DAILYBUILD_V100",
    "OPENWRT_DAILYBUILD_V100",
    "OPENWRT_DAILYBUILD_MASTER",
    "ZEPHYROS_DAILYBUILD",
    "GDM7275X_LINUXOS_MASTER_DAILYBUILD",
    "GDM7243A_UTKERNEL_DAILYBUILD",
    "GDM7243ST_UTKERNEL_DAILYBUILD",
    "GDM7243I_ZEPHYR_V2_3_DAILYBUILD",
    "DAILYBUILD_MAIL_NOTIFIER",
]


def _daily_cron_jobs() -> list[tuple[str, str, str, str, str]]:
    return [
        ("0 3 * * *", "run-openwrt", "openwrt_v1.00_dailybuild.env", "openwrt/v1.00/cron_runner.log", "# OPENWRT_DAILYBUILD_V100"),
        ("1 3 * * *", "run-openwrt", "openwrt_master_dailybuild.env", "openwrt/master/cron_runner.log", "# OPENWRT_DAILYBUILD_MASTER"),
        ("2 3 * * *", "run-os", "gdm7275x_linuxos_master_dailybuild.env", "linuxos/gdm7275x/cron_runner.log", "# GDM7275X_LINUXOS_MASTER_DAILYBUILD"),
        ("3 3 * * *", "run-zephyros", "zephyros_dailybuild.env", "zephyros/cron_runner.log", "# ZEPHYROS_DAILYBUILD"),
        ("4 3 * * *", "run-os", "gdm7243a_utkernel_dailybuild.env", "uTKernel/gdm7243a/cron_runner.log", "# GDM7243A_UTKERNEL_DAILYBUILD"),
        ("5 3 * * *", "run-os", "gdm7243st_utkernel_dailybuild.env", "uTKernel/gdm7243st/cron_runner.log", "# GDM7243ST_UTKERNEL_DAILYBUILD"),
        ("6 3 * * *", "run-os", "gdm7243i_zephyr_v2.3_dailybuild.env", "zephyr_v2_3/gdm7243i/cron_runner.log", "# GDM7243I_ZEPHYR_V2_3_DAILYBUILD"),
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
    env = merged_env(config_root / "dailybuild_common.env")
    entrypoint = repo_root / "dailybuild.py"
    log_root = DailybuildPaths.from_env(env).log_root
    lines = []
    for schedule, subcommand, config_name, log_rel, tag in _daily_cron_jobs():
        config_file = config_root / config_name
        log_file = log_root / log_rel
        line = f"{schedule} {_q(entrypoint)} {subcommand} --config {_q(config_file)} >> {_q(log_file)} 2>&1 {tag}"
        lines.append(line)
    notifier_log = log_root / "notifier/dailybuild_mail_notifier.log"
    common_config = config_root / "dailybuild_common.env"
    lines.append(f"*/10 * * * * {_q(entrypoint)} notify --config {_q(common_config)} >> {_q(notifier_log)} 2>&1 # DAILYBUILD_MAIL_NOTIFIER")
    return lines


def _validate_daily_cron_inputs() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    config_root = _config_root(repo_root)
    env = merged_env(config_root / "dailybuild_common.env")
    required = [config_root / "dailybuild_common.env"]
    required.extend(config_root / job[2] for job in _daily_cron_jobs())
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("Missing required config file(s):\n" + "\n".join(missing))

    upload_dir = merged_env(config_root / "dailybuild_common.env").get("SAMBA_UPLOAD_LOCAL_DIR", "")
    if upload_dir and not os.access(upload_dir, os.W_OK):
        raise SystemExit(f"Samba upload local dir is not writable: {upload_dir}")

    log_root = DailybuildPaths.from_env(env).log_root
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
    env = merged_env(config_root / "dailybuild_common.env")
    paths = DailybuildPaths.from_env(env)
    entrypoint = repo_root / "dailybuild.py"
    log_root = paths.log_root
    state_root = paths.state_root
    start_after = int(env.get("START_AFTER_MINUTES", "1"))
    notifier_start = int(env.get("NOTIFIER_START_AFTER_MINUTES", str(start_after + 10)))
    notifier_interval = int(env.get("NOTIFIER_INTERVAL_MINUTES", "10"))
    notifier_repeat = int(env.get("NOTIFIER_REPEAT_COUNT", "72"))
    max_runtime_minutes = int(env.get("TEST_ONCE_MAX_RUNTIME_MINUTES", "180"))
    deadline_epoch = int((dt.datetime.now() + dt.timedelta(minutes=max_runtime_minutes)).timestamp())
    test_run_ts = env.get("TEST_RUN_TS", dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
    run_date = env.get("RUN_DATE", test_run_ts.split("_", 1)[0])
    subject_prefix = env.get("TEST_REPORT_SUBJECT_PREFIX", "[TestPy]")
    mail_to = env.get("TEST_MAIL_TO", "jamesahn@gctsemi.com")
    status_file = state_root / f"one_time_dailybuild_status_{test_run_ts}.txt"
    sent_flag = state_root / f".one_time_dailybuild_mail_sent_{test_run_ts}.flag"
    upload_flag = state_root / f".one_time_dailybuild_logs_uploaded_{test_run_ts}.flag"
    upload_subdir = f"Test/{test_run_ts}"

    build_jobs = [
        (0, "GDM7275X OpenWrt v1.00", "run-openwrt", config_root / "openwrt_v1.00_dailybuild.env", log_root / "openwrt/v1.00/cron_runner.log"),
        (1, "GDM7275X OpenWrt master", "run-openwrt", config_root / "openwrt_master_dailybuild.env", log_root / "openwrt/master/cron_runner.log"),
        (2, "GDM7275X Linuxos master", "run-os", config_root / "gdm7275x_linuxos_master_dailybuild.env", log_root / "linuxos/gdm7275x/cron_runner.log"),
        (3, "GDM7275X Zephyros", "run-zephyros", config_root / "zephyros_dailybuild.env", log_root / "zephyros/cron_runner.log"),
        (4, "GDM7243A uTKernel", "run-os", config_root / "gdm7243a_utkernel_dailybuild.env", log_root / "uTKernel/gdm7243a/cron_runner.log"),
        (5, "GDM7243ST uTKernel", "run-os", config_root / "gdm7243st_utkernel_dailybuild.env", log_root / "uTKernel/gdm7243st/cron_runner.log"),
        (6, "GDM7243i zephyr-v2.3", "run-os", config_root / "gdm7243i_zephyr_v2.3_dailybuild.env", log_root / "zephyr_v2_3/gdm7243i/cron_runner.log"),
    ]
    state_root.mkdir(parents=True, exist_ok=True)
    commands: list[ScheduledCommand] = []
    expiry_guard = _expiry_guard(deadline_epoch, test_run_ts)
    for offset, label, subcommand, config, log_file in build_jobs:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        env_prefix = _shell_env(DAILY_STATUS_FILE=status_file)
        command = f"{expiry_guard}; {env_prefix} {_q(entrypoint)} {subcommand} --config {_q(config)} >> {_q(log_file)} 2>&1"
        commands.append(ScheduledCommand(start_after + offset, label, command))

    notifier_log = log_root / "notifier/dailybuild_mail_notifier.log"
    notifier_log.parent.mkdir(parents=True, exist_ok=True)
    for idx in range(notifier_repeat):
        offset = notifier_start + idx * notifier_interval
        if offset > max_runtime_minutes:
            break
        env_prefix = _shell_env(
            RUN_DATE=run_date,
            MIN_RUN_TS=test_run_ts,
            DAILY_STATUS_FILE=status_file,
            MAIL_TO=mail_to,
            REPORT_SUBJECT_PREFIX=subject_prefix,
            SENT_FLAG_FILE=sent_flag,
            UPLOAD_FLAG_FILE=upload_flag,
            SAMBA_UPLOAD_SUBDIR=upload_subdir,
        )
        done_guard = f"if [ -f {_q(sent_flag)} ] && [ -f {_q(upload_flag)} ]; then exit 0; fi"
        command = f"{expiry_guard}; {done_guard}; {env_prefix} {_q(entrypoint)} notify --run-date {_q(run_date)} --config {_q(config_root / 'dailybuild_common.env')} --min-run-ts {_q(test_run_ts)} >> {_q(notifier_log)} 2>&1"
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


def list_jobs(args) -> int:
    env = merged_env(getattr(args, "config", "config/dailybuild_common.env"))
    paths = DailybuildPaths.from_env(env)
    config_root = _config_root(Path(__file__).resolve().parents[1])

    print("Daily Cron Jobs")
    print("---------------")
    for schedule, subcommand, config_name, log_rel, tag in _daily_cron_jobs():
        print(f"{schedule}  {subcommand:12}  {config_name}  -> {paths.log_root / log_rel} {tag}")
    print(f"*/10 * * * *  {'notify':12}  dailybuild_common.env -> {paths.log_root / 'notifier/dailybuild_mail_notifier.log'} # DAILYBUILD_MAIL_NOTIFIER")
    print()

    print("One-Time Tests")
    print("--------------")
    one_time_rows = _one_time_test_rows(paths.state_root)
    if not one_time_rows:
        print("[none]")
    else:
        for row in one_time_rows:
            state = "completed" if row["sent_exists"] and row["upload_exists"] else "pending"
            print(
                f"{row['test_run_ts']}  state={state}  run_date={row['run_date']}  "
                f"status={'yes' if row['status_exists'] else 'no'}  "
                f"sent={'yes' if row['sent_exists'] else 'no'}  "
                f"uploaded={'yes' if row['upload_exists'] else 'no'}"
            )
            print(f"  status_file: {row['status_file']}")
    scheduler_log = paths.log_root / "notifier/one_time_daily_test_scheduler.log"
    if scheduler_log.exists():
        print(f"  scheduler_log: {scheduler_log}")
    print()

    print("Running Processes")
    print("-----------------")
    running = _running_dailybuild_processes()
    if not running:
        print("[none]")
    else:
        for row in running:
            print(f"{row['pid']:>6}  {row['command_name']:12}  {row['cmd']}")
    return 0


def _one_time_test_rows(state_root: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for status_file in sorted(state_root.glob("one_time_dailybuild_status_*.txt")):
        test_run_ts = status_file.stem.removeprefix("one_time_dailybuild_status_")
        run_date = test_run_ts.split("_", 1)[0]
        sent_flag = state_root / f".one_time_dailybuild_mail_sent_{test_run_ts}.flag"
        upload_flag = state_root / f".one_time_dailybuild_logs_uploaded_{test_run_ts}.flag"
        rows.append({
            "test_run_ts": test_run_ts,
            "run_date": run_date,
            "status_file": status_file,
            "status_exists": status_file.exists(),
            "sent_exists": sent_flag.exists(),
            "upload_exists": upload_flag.exists(),
        })
    rows.sort(key=lambda row: str(row["test_run_ts"]), reverse=True)
    return rows


def _running_dailybuild_processes() -> list[dict[str, str]]:
    proc = subprocess.run(["ps", "-eo", "pid=,args="], text=True, capture_output=True, check=True)
    return _parse_ps_output(proc.stdout)


def _parse_ps_output(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        pid, cmd = parts
        if "dailybuild.py" not in cmd:
            continue
        if " list-jobs" in cmd:
            continue
        cmd_parts = cmd.split()
        command_name = "dailybuild.py"
        try:
            index = next(i for i, part in enumerate(cmd_parts) if part.endswith("dailybuild.py"))
            if index + 1 < len(cmd_parts):
                command_name = cmd_parts[index + 1]
        except StopIteration:
            pass
        rows.append({"pid": pid, "cmd": cmd, "command_name": command_name})
    return rows


def _config_root(repo_root: Path) -> Path:
    return Path(os.environ.get("DAILYBUILD_CONFIG_ROOT", repo_root / "config")).expanduser()
