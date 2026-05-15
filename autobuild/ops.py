"""Operational CLI helpers for config and status inspection."""

from __future__ import annotations

import shlex
from pathlib import Path
from types import SimpleNamespace

from .config import daily_status_file, load_env_file, merged_env, today
from .status import parse_status_file
from . import scheduler


CONFIG_GROUPS = [
    ("Mail", [
        "EMAIL_NOTI_ENABLED",
        "MAIL_FROM",
        "MAIL_FROM_NAME",
        "MAIL_REPLY_TO",
        "MAIL_TO",
        "REPORT_SUBJECT_PREFIX",
    ]),
    ("SMTP", [
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USER",
        "SMTP_USE_STARTTLS",
        "SMTP_INSECURE_TLS",
    ]),
    ("Paths", [
        "AUTOBUILD_ROOT",
        "AUTOBUILD_LOG_ROOT",
        "AUTOBUILD_TMP_ROOT",
        "AUTOBUILD_STATE_ROOT",
    ]),
    ("Samba", [
        "SAMBA_UPLOAD_ENABLED",
        "SAMBA_UPLOAD_URI",
        "SAMBA_UPLOAD_UNC_ROOT",
        "SAMBA_UPLOAD_LOCAL_DIR",
    ]),
    ("One-Time Test", [
        "TEST_MAIL_TO",
        "TEST_REPORT_SUBJECT_PREFIX",
        "START_AFTER_MINUTES",
        "TEST_ONCE_MAX_RUNTIME_MINUTES",
    ]),
]

INTERACTIVE_CONFIG_OPTIONS = [
    ("MAIL_TO", "Mail recipients"),
    ("REPORT_SUBJECT_PREFIX", "Mail subject prefix"),
    ("TEST_MAIL_TO", "One-time test mail recipients"),
    ("TEST_REPORT_SUBJECT_PREFIX", "One-time test subject prefix"),
    ("SAMBA_UPLOAD_LOCAL_DIR", "Samba local dir"),
    ("SAMBA_UPLOAD_UNC_ROOT", "Samba UNC root"),
    ("EMAIL_NOTI_ENABLED", "Email notification enabled (0/1)"),
]


def show_config(args) -> int:
    config_path = Path(getattr(args, "config", "config/autobuild_common.env")).expanduser()
    values = load_env_file(config_path)
    merged = merged_env(config_path)
    print(f"Config file: {config_path}")
    print()
    for title, keys in CONFIG_GROUPS:
        print(title)
        print("-" * len(title))
        for key in keys:
            source = values.get(key, "")
            effective = merged.get(key, "")
            suffix = "" if source == effective else f"  (effective: {effective})"
            print(f"{key}={source}{suffix}")
        print()
    return 0


def set_config(args) -> int:
    config_path = Path(getattr(args, "config", "config/autobuild_common.env")).expanduser()
    updates = _collect_updates(args)
    if not updates:
        raise SystemExit("No config updates requested")
    return _apply_config_updates(config_path, updates, getattr(args, "show_after", False))


def show_status(args) -> int:
    run_date = getattr(args, "run_date", None) or today()
    overrides = {"RUN_DATE": run_date}
    if getattr(args, "status_file", None):
        overrides["DAILY_STATUS_FILE"] = args.status_file
    env = merged_env(getattr(args, "config", "config/autobuild_common.env"), overrides)
    status_path = Path(getattr(args, "status_file", None) or daily_status_file(env, run_date))
    if not status_path.exists():
        print(f"[WARN] Status file not found: {status_path}")
        return 1

    sections = parse_status_file(status_path)
    counts: dict[str, int] = {}
    for section in sections:
        result = section.fields.get("Result") or section.fields.get("Status") or "UNKNOWN"
        counts[result] = counts.get(result, 0) + 1

    print(f"Status file: {status_path}")
    print(f"Run date   : {run_date}")
    if counts:
        summary = ", ".join(f"{key}={counts[key]}" for key in sorted(counts))
        print(f"Summary    : {summary}")
    else:
        print("Summary    : no sections found")
    print()
    for section in sections:
        result = section.fields.get("Result") or section.fields.get("Status") or "UNKNOWN"
        duration = section.fields.get("Duration", "")
        run_ts = section.fields.get("Run ts", "")
        fail_reason = section.fields.get("Fail reason", "")
        print(f"[{section.name}] {result}")
        if run_ts:
            print(f"  run_ts   : {run_ts}")
        if duration:
            print(f"  duration : {duration}")
        if fail_reason:
            print(f"  fail     : {fail_reason}")
    if getattr(args, "raw", False):
        print()
        print("Raw Status")
        print("----------")
        print(status_path.read_text(encoding="utf-8"), end="")
    return 0


def interactive(args) -> int:
    config_path = Path(getattr(args, "config", "config/autobuild_common.env")).expanduser()
    while True:
        print("Interactive Operations")
        print("----------------------")
        print("1. Show config")
        print("2. Update config")
        print("3. Show status")
        print("4. List jobs")
        print("5. Schedule one-time test")
        print("6. Help summary")
        print("0. Exit")
        choice = _prompt("Select menu", "0").strip()
        print()
        if choice == "1":
            show_config(SimpleNamespace(config=str(config_path)))
        elif choice == "2":
            _interactive_update_config(config_path)
        elif choice == "3":
            _interactive_show_status(config_path)
        elif choice == "4":
            scheduler.list_jobs(SimpleNamespace(config=str(config_path)))
        elif choice == "5":
            _interactive_schedule_one_time(config_path)
        elif choice == "6":
            _print_help_summary()
        elif choice == "0":
            print("Bye.")
            return 0
        else:
            print(f"[WARN] Unknown menu: {choice}")
        print()


def _collect_updates(args) -> dict[str, str]:
    updates: dict[str, str] = {}
    mapping = {
        "mail_to": "MAIL_TO",
        "subject_prefix": "REPORT_SUBJECT_PREFIX",
        "test_mail_to": "TEST_MAIL_TO",
        "test_subject_prefix": "TEST_REPORT_SUBJECT_PREFIX",
        "samba_local_dir": "SAMBA_UPLOAD_LOCAL_DIR",
        "samba_unc_root": "SAMBA_UPLOAD_UNC_ROOT",
        "email_noti_enabled": "EMAIL_NOTI_ENABLED",
    }
    for attr, key in mapping.items():
        value = getattr(args, attr, None)
        if value is not None:
            updates[key] = value
    for item in getattr(args, "set_values", []) or []:
        if "=" not in item:
            raise SystemExit(f"Invalid --set value: {item} (expected KEY=VALUE)")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise SystemExit(f"Invalid --set key in: {item}")
        updates[key] = value
    return updates


def _apply_config_updates(config_path: Path, updates: dict[str, str], show_after: bool) -> int:
    _update_env_file(config_path, updates)
    print(f"[INFO] Updated config: {config_path}")
    for key, value in updates.items():
        print(f"{key}={value}")
    if show_after:
        print()
        show_config(SimpleNamespace(config=str(config_path)))
    return 0


def _interactive_update_config(config_path: Path) -> None:
    current = load_env_file(config_path)
    print("Update Config")
    print("-------------")
    for index, (key, label) in enumerate(INTERACTIVE_CONFIG_OPTIONS, start=1):
        print(f"{index}. {label} [{key}] = {current.get(key, '')}")
    extra_index = len(INTERACTIVE_CONFIG_OPTIONS) + 1
    print(f"{extra_index}. Generic KEY=VALUE")
    print("0. Back")
    choice = _prompt("Select config item", "0").strip()
    if choice == "0":
        return
    if choice == str(extra_index):
        raw = _prompt("Enter KEY=VALUE", "").strip()
        if not raw:
            print("[INFO] No update entered")
            return
        if "=" not in raw:
            print("[WARN] Expected KEY=VALUE")
            return
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key:
            print("[WARN] Empty key")
            return
        _apply_config_updates(config_path, {key: value}, show_after=False)
        return
    try:
        selected = int(choice)
    except ValueError:
        print(f"[WARN] Invalid selection: {choice}")
        return
    if not 1 <= selected <= len(INTERACTIVE_CONFIG_OPTIONS):
        print(f"[WARN] Invalid selection: {choice}")
        return
    key, label = INTERACTIVE_CONFIG_OPTIONS[selected - 1]
    default = current.get(key, "")
    value = _prompt(f"{label} [{key}]", default)
    if value == default:
        print("[INFO] No change")
        return
    _apply_config_updates(config_path, {key: value}, show_after=False)


def _interactive_show_status(config_path: Path) -> None:
    run_date = _prompt("Run date (YYYYMMDD)", today()).strip() or today()
    env = merged_env(str(config_path), {"RUN_DATE": run_date})
    status_path = Path(daily_status_file(env, run_date))
    if not status_path.exists():
        print(f"[WARN] Status file not found: {status_path}")
        return

    sections = parse_status_file(status_path)
    counts: dict[str, int] = {}
    failed_sections: list[str] = []
    for section in sections:
        result = section.fields.get("Result") or section.fields.get("Status") or "UNKNOWN"
        counts[result] = counts.get(result, 0) + 1
        if result == "FAIL":
            failed_sections.append(section.name)

    print(f"Status file: {status_path}")
    summary = ", ".join(f"{key}={counts[key]}" for key in sorted(counts)) if counts else "no sections found"
    print(f"Summary    : {summary}")
    if failed_sections:
        print("Failed     : " + ", ".join(failed_sections))
    print()
    for index, section in enumerate(sections, start=1):
        result = section.fields.get("Result") or section.fields.get("Status") or "UNKNOWN"
        duration = section.fields.get("Duration", "")
        run_ts = section.fields.get("Run ts", "")
        fail_reason = section.fields.get("Fail reason", "")
        line = f"{index}. [{section.name}] {result}"
        if duration:
            line += f"  duration={duration}"
        if run_ts:
            line += f"  run_ts={run_ts}"
        print(line)
        if fail_reason:
            print(f"   fail={fail_reason}")

    print()
    choice = _prompt("Detail view: section number, 'f' for fails, 'r' for raw, Enter to continue", "")
    choice = choice.strip().lower()
    if not choice:
        return
    if choice == "r":
        print()
        print("Raw Status")
        print("----------")
        print(status_path.read_text(encoding="utf-8"), end="")
        return
    targets: list[object]
    if choice == "f":
        targets = [section for section in sections if (section.fields.get("Result") or section.fields.get("Status") or "UNKNOWN") == "FAIL"]
        if not targets:
            print("[INFO] No failed sections")
            return
    else:
        try:
            selected = int(choice)
        except ValueError:
            print(f"[WARN] Invalid selection: {choice}")
            return
        if not 1 <= selected <= len(sections):
            print(f"[WARN] Invalid selection: {choice}")
            return
        targets = [sections[selected - 1]]

    for section in targets:
        print()
        print(f"[{section.name}]")
        print("-" * (len(section.name) + 2))
        for key, value in section.fields.items():
            print(f"{key}: {value}")
        if section.git_log:
            print("Git log:")
            for line in section.git_log:
                print(f"  {line}")


def _interactive_schedule_one_time(config_path: Path) -> None:
    dry_run = _prompt("Dry-run only? (Y/n)", "y").strip().lower() not in {"n", "no"}
    if not dry_run:
        confirmed = _prompt("Schedule one-time test now? (y/N)", "n").strip().lower() in {"y", "yes"}
        if not confirmed:
            print("[INFO] One-time scheduling cancelled")
            return
    scheduler.test_once(SimpleNamespace(config=str(config_path), dry_run=dry_run))


def _print_help_summary() -> None:
    print("Quick Commands")
    print("--------------")
    print("show-config               Show managed configuration")
    print("set-config --mail-to ...  Update config values")
    print("show-status --run-date    Show daily build summary")
    print("list-jobs                 Show cron, one-time state, and running processes")
    print("test-once                 Schedule a one-time full test")
    print("tail-logs                 Follow all cron logs")


def _prompt(label: str, default: str) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ")
    return value if value.strip() else default


def _update_env_file(path: Path, updates: dict[str, str]) -> None:
    if not path.exists():
        raise SystemExit(f"Missing config file: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    remaining = dict(updates)
    rendered: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            rendered.append(line)
            continue
        key, _ = line.split("=", 1)
        key = key.strip()
        if key in remaining:
            rendered.append(f"{key}={shlex.quote(str(remaining.pop(key)))}")
        else:
            rendered.append(line)
    if remaining:
        if rendered and rendered[-1] != "":
            rendered.append("")
        for key, value in remaining.items():
            rendered.append(f"{key}={shlex.quote(str(value))}")
    path.write_text("\n".join(rendered) + "\n", encoding="utf-8")
