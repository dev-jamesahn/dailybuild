#!/usr/bin/env python3
"""Daily autobuild command entrypoint."""

from __future__ import annotations

import argparse
import sys

from autobuild import mail, runner, scheduler, upload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="autobuild.py")
    sub = parser.add_subparsers(dest="command", required=True)

    install_cron = sub.add_parser("install-cron", help="Install daily autobuild cron jobs")
    install_cron.add_argument("--dry-run", action="store_true", help="Print cron commands only")
    install_cron.set_defaults(func=scheduler.install_cron)

    run_openwrt = sub.add_parser("run-openwrt", help="Run an OpenWrt autobuild")
    run_openwrt.add_argument("--config", required=True, help="Path to OpenWrt env config")
    run_openwrt.set_defaults(func=runner.run_openwrt)

    run_os = sub.add_parser("run-os", help="Run an OS autobuild")
    run_os.add_argument("--config", required=True, help="Path to OS env config")
    run_os.set_defaults(func=runner.run_os)

    run_zephyros = sub.add_parser("run-zephyros", help="Run a Zephyros autobuild")
    run_zephyros.add_argument("--config", required=True, help="Path to Zephyros env config")
    run_zephyros.set_defaults(func=runner.run_zephyros)

    upload_cmd = sub.add_parser("upload", help="Upload daily logs and images")
    upload_cmd.add_argument("--run-date", help="Run date in YYYYMMDD format")
    upload_cmd.add_argument("--config", default="config/autobuild_common.env")
    upload_cmd.add_argument("--status-file", help="Override daily status file path")
    upload_cmd.add_argument("--output-dir", help="Override local upload root for testing")
    upload_cmd.set_defaults(func=upload.run)

    notify = sub.add_parser("notify", help="Send daily report mail")
    notify.add_argument("--run-date", help="Run date in YYYYMMDD format")
    notify.add_argument("--config", default="config/autobuild_common.env")
    notify.add_argument("--status-file", help="Override daily status file path")
    notify.set_defaults(func=mail.notify)

    test_once = sub.add_parser("test-once", help="Schedule a one-time full daily test")
    test_once.add_argument("--dry-run", action="store_true")
    test_once.set_defaults(func=scheduler.test_once)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
