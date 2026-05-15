#!/usr/bin/env python3
"""Daily autobuild command entrypoint."""

from __future__ import annotations

import argparse
import sys

from autobuild import logtail, mail, ops, runner, scheduler, status as status_mod, upload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="autobuild.py")
    sub = parser.add_subparsers(dest="command", required=True)

    install_cron = sub.add_parser("install-cron", help="Install daily autobuild cron jobs")
    install_cron.add_argument("--dry-run", action="store_true", help="Print cron commands only")
    install_cron.set_defaults(func=scheduler.install_cron)

    run_openwrt = sub.add_parser("run-openwrt", help="Run an OpenWrt autobuild")
    run_openwrt.add_argument("--config", required=True, help="Path to OpenWrt env config")
    run_openwrt.add_argument("--dry-run", action="store_true", help="Print the OpenWrt run settings without running it")
    run_openwrt.set_defaults(func=runner.run_openwrt)

    run_os = sub.add_parser("run-os", help="Run an OS autobuild")
    run_os.add_argument("--config", required=True, help="Path to OS env config")
    run_os.add_argument("--dry-run", action="store_true", help="Print the OS run settings without running it")
    run_os.set_defaults(func=runner.run_os)

    run_zephyros = sub.add_parser("run-zephyros", help="Run a Zephyros autobuild")
    run_zephyros.add_argument("--config", required=True, help="Path to Zephyros env config")
    run_zephyros.add_argument("--dry-run", action="store_true", help="Print the legacy command without running it")
    run_zephyros.set_defaults(func=runner.run_zephyros)

    upload_cmd = sub.add_parser("upload", help="Upload daily logs and images")
    upload_cmd.add_argument("--run-date", help="Run date in YYYYMMDD format")
    upload_cmd.add_argument("--config", default="config/autobuild_common.env")
    upload_cmd.add_argument("--status-file", help="Override daily status file path")
    upload_cmd.add_argument("--output-dir", help="Override local upload root for testing")
    upload_cmd.add_argument("--upload-subdir", help="Override upload subdirectory under the Samba root")
    upload_cmd.add_argument("--force", action="store_true", help="Upload even when the upload flag already exists")
    upload_cmd.set_defaults(func=upload.run)

    notify = sub.add_parser("notify", help="Send daily report mail")
    notify.add_argument("--run-date", help="Run date in YYYYMMDD format")
    notify.add_argument("--config", default="config/autobuild_common.env")
    notify.add_argument("--status-file", help="Override daily status file path")
    notify.add_argument("--min-run-ts", help="Require summary RUN_TS to be at least this value")
    notify.add_argument("--force", action="store_true", help="Send even when the sent flag already exists")
    notify.set_defaults(func=mail.notify)

    show_config = sub.add_parser("show-config", help="Show managed runtime configuration values")
    show_config.add_argument("--config", default="config/autobuild_common.env")
    show_config.set_defaults(func=ops.show_config)

    set_config = sub.add_parser("set-config", help="Update managed runtime configuration values")
    set_config.add_argument("--config", default="config/autobuild_common.env")
    set_config.add_argument("--mail-to", dest="mail_to", help="Update MAIL_TO")
    set_config.add_argument("--subject-prefix", dest="subject_prefix", help="Update REPORT_SUBJECT_PREFIX")
    set_config.add_argument("--test-mail-to", dest="test_mail_to", help="Update TEST_MAIL_TO")
    set_config.add_argument("--test-subject-prefix", dest="test_subject_prefix", help="Update TEST_REPORT_SUBJECT_PREFIX")
    set_config.add_argument("--samba-local-dir", dest="samba_local_dir", help="Update SAMBA_UPLOAD_LOCAL_DIR")
    set_config.add_argument("--samba-unc-root", dest="samba_unc_root", help="Update SAMBA_UPLOAD_UNC_ROOT")
    set_config.add_argument("--email-noti-enabled", dest="email_noti_enabled", choices=["0", "1"], help="Update EMAIL_NOTI_ENABLED")
    set_config.add_argument("--set", dest="set_values", action="append", help="Generic KEY=VALUE update, repeatable")
    set_config.add_argument("--show-after", action="store_true", help="Print show-config output after updating")
    set_config.set_defaults(func=ops.set_config)

    show_status = sub.add_parser("show-status", help="Show summarized daily status for a run date")
    show_status.add_argument("--run-date", help="Run date in YYYYMMDD format")
    show_status.add_argument("--config", default="config/autobuild_common.env")
    show_status.add_argument("--status-file", help="Override daily status file path")
    show_status.add_argument("--raw", action="store_true", help="Print the raw status file after the summary")
    show_status.set_defaults(func=ops.show_status)

    status = sub.add_parser("status", help="Generate a daily status file from latest summaries")
    status.add_argument("--run-date", help="Run date in YYYYMMDD format")
    status.add_argument("--config", default="config/autobuild_common.env")
    status.add_argument("--output", help="Override output status file")
    status.set_defaults(func=status_mod.write_daily_status_command)

    test_once = sub.add_parser("test-once", help="Schedule a one-time full daily test")
    test_once.add_argument("--dry-run", action="store_true")
    test_once.set_defaults(func=scheduler.test_once)

    list_jobs = sub.add_parser("list-jobs", help="Show daily cron jobs, one-time test state, and running autobuild processes")
    list_jobs.add_argument("--config", default="config/autobuild_common.env")
    list_jobs.set_defaults(func=scheduler.list_jobs)

    tail_logs = sub.add_parser("tail-logs", help="Follow all daily build cron logs with target prefixes")
    tail_logs.add_argument("--config", default="config/autobuild_common.env")
    tail_logs.add_argument("--lines", type=int, default=20, help="Initial lines to print per existing log")
    tail_logs.add_argument("--interval", type=float, default=1.0, help="Polling interval in seconds")
    tail_logs.add_argument("--no-follow", action="store_true", help="Print current log tails and exit")
    tail_logs.set_defaults(func=logtail.tail_logs)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
