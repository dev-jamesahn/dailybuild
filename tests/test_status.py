from pathlib import Path
from tempfile import TemporaryDirectory
import datetime as dt
import unittest

from autobuild.status import discover_os_summary_files, format_target_status, generate_daily_status, generate_fw_build_info, parse_status_file


class StatusTests(unittest.TestCase):
    def test_parse_status_file_collects_fields_and_git_log(self):
        with TemporaryDirectory() as tmp:
            status_file = Path(tmp) / "daily.txt"
            status_file.write_text(
                "\n".join([
                    "[GDM7275X OpenWrt v1.00]",
                    "Result      : SUCCESS",
                    "Duration    : 00:10:00",
                    "Git log     :",
                    "  commit : abc123",
                    "  author : dev-jamesahn <ahw1103@gmail.com>",
                    "Log path    : /tmp/build.log",
                    "",
                ]),
                encoding="utf-8",
            )

            sections = parse_status_file(status_file)

        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0].name, "GDM7275X OpenWrt v1.00")
        self.assertEqual(sections[0].fields["Result"], "SUCCESS")
        self.assertEqual(sections[0].git_log[0], "commit : abc123")

    def test_generate_fw_build_info_uses_na_for_missing_entries(self):
        with TemporaryDirectory() as tmp:
            status_file = Path(tmp) / "daily.txt"
            status_file.write_text(
                "\n".join([
                    "[GDM7275X OpenWrt v1.00]",
                    "Git log     :",
                    "  commit : abc123",
                    "  author : dev-jamesahn <ahw1103@gmail.com>",
                    "  date   : 2026-05-13T00:00:00+09:00",
                    "  subject: sample",
                    "",
                ]),
                encoding="utf-8",
            )

            fw_info = generate_fw_build_info(status_file)

        self.assertIn("[GDM7275X]", fw_info)
        self.assertIn("  - OpenWRT v1.00", fw_info)
        self.assertIn("    commit : abc123", fw_info)
        self.assertIn("  - OpenWRT master", fw_info)
        self.assertIn("    commit : N/A", fw_info)

    def test_format_target_status_from_summary(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            hash_log = root / "hash.log"
            hash_log.write_text("GDM|desc|gdm123\nSBL|desc|sbl123\n", encoding="utf-8")
            summary = root / "latest_summary.env"
            summary.write_text(
                "\n".join([
                    "TARGET_NAME='GDM7275X OpenWrt v1.00'",
                    "BUILD_RESULT=SUCCESS",
                    "CURRENT_STAGE=done",
                    "BUILD_STARTED_AT='2026-05-13 00:00:00'",
                    "BUILD_ENDED_AT='2026-05-13 00:10:00'",
                    "BUILD_DURATION_FMT='00:10:00'",
                    "RUN_TS=20260513_000000",
                    "BUILD_LOG='/tmp/build.log'",
                    "MAIN_REPO_LAST_COMMIT=abc123",
                    "MAIN_REPO_LAST_AUTHOR='dev-jamesahn <ahw1103@gmail.com>'",
                    "MAIN_REPO_LAST_DATE='2026-05-13T00:00:00+09:00'",
                    "MAIN_REPO_LAST_SUBJECT='sample'",
                    f"HASH_LOG='{hash_log}'",
                ]),
                encoding="utf-8",
            )

            text = format_target_status("OpenWrt v1.00", summary)

        self.assertIn("[GDM7275X OpenWrt v1.00]", text)
        self.assertIn("Result       : SUCCESS", text)
        self.assertIn("Git log      :", text)
        self.assertIn("  GDM   : gdm123", text)

    def test_generate_daily_status_includes_default_not_run_and_os_summaries(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            os_dir = root / "uTKernel/gdm7243a"
            os_dir.mkdir(parents=True)
            (os_dir / "latest_summary.env").write_text(
                "\n".join([
                    "TARGET_NAME='GDM7243A uTKernel - gdm7243a_no_l2'",
                    "BUILD_RESULT=FAIL",
                    "RUN_TS=20260513_010000",
                ]),
                encoding="utf-8",
            )

            text = generate_daily_status(root, generated_at=dt.datetime(2026, 5, 13, 1, 0, 0))
            discovered = discover_os_summary_files(root)

        self.assertIn("[OpenWrt v1.00]\nStatus       : NOT_RUN", text)
        self.assertIn("[GDM7243A uTKernel - gdm7243a_no_l2]", text)
        self.assertEqual(len(discovered), 1)


if __name__ == "__main__":
    unittest.main()
