from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from autobuild.status import generate_fw_build_info, parse_status_file


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


if __name__ == "__main__":
    unittest.main()
