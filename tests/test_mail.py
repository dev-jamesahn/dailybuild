from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from autobuild.mail import summary_ready_for_today


class MailTests(unittest.TestCase):
    def test_summary_ready_for_today_requires_run_date_and_end_fields(self):
        with TemporaryDirectory() as tmp:
            summary = Path(tmp) / "latest_summary.env"
            summary.write_text(
                "\n".join([
                    "RUN_TS=20260513_010000",
                    "BUILD_RESULT=SUCCESS",
                    "BUILD_ENDED_AT='2026-05-13 01:10:00'",
                ]),
                encoding="utf-8",
            )

            self.assertTrue(summary_ready_for_today(summary, "20260513"))
            self.assertFalse(summary_ready_for_today(summary, "20260512"))
            self.assertFalse(summary_ready_for_today(summary, "20260513", "20260513_020000"))

    def test_summary_ready_for_today_rejects_missing_result(self):
        with TemporaryDirectory() as tmp:
            summary = Path(tmp) / "latest_summary.env"
            summary.write_text("RUN_TS=20260513_010000\n", encoding="utf-8")

            self.assertFalse(summary_ready_for_today(summary, "20260513"))


if __name__ == "__main__":
    unittest.main()
