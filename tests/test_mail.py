from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.mail import build_html, summary_ready_for_today


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

    def test_build_html_uses_upload_subdir_for_samba_paths(self):
        with TemporaryDirectory() as tmp:
            status = Path(tmp) / "status.txt"
            status.write_text(
                "\n".join([
                    "[GDM7275X Linuxos master]",
                    "Result       : SUCCESS",
                    "Duration     : 00:01:00",
                ]),
                encoding="utf-8",
            )

            html = build_html(status, "[TestPy] Report", "20260513", r"K:\ENG\ENG05\CS_team\James", Path("Test/20260513_145122"))

        self.assertIn("<strong>Log :</strong>", html)
        self.assertIn("<strong>Image :</strong>", html)
        self.assertIn(r"K:\ENG\ENG05\CS_team\James\Test\20260513_145122\GDM7275X\linuxos_master\Log", html)

    def test_build_html_includes_manifest_hash_for_openwrt(self):
        with TemporaryDirectory() as tmp:
            status = Path(tmp) / "status.txt"
            status.write_text(
                "\n".join([
                    "[GDM7275X OpenWrt v1.00]",
                    "Result       : SUCCESS",
                    "Git log      :",
                    "  commit : abc123",
                    "Manifest hashes:",
                    "  GDM   : gdmhash",
                    "  SBL   : sblhash",
                    "  UBOOT : uboothash",
                ]),
                encoding="utf-8",
            )

            html = build_html(status, "[TestPy] Report", "20260513", r"K:\ENG\ENG05\CS_team\James")

        self.assertIn("<strong>Manifest hash:</strong>", html)
        self.assertIn("GDM : gdmhash", html)
        self.assertIn("SBL : sblhash", html)
        self.assertIn("UBOOT : uboothash", html)

    def test_build_html_uses_fail_reason_when_failure_analysis_missing(self):
        with TemporaryDirectory() as tmp:
            status = Path(tmp) / "status.txt"
            status.write_text(
                "\n".join([
                    "[GDM7275X Zephyros]",
                    "Result       : FAIL",
                    "Fail reason  : Zephyros config prompt not found",
                ]),
                encoding="utf-8",
            )

            html = build_html(status, "[TestPy] Report", "20260515", r"K:\ENG\ENG05\CS_team\James")

        self.assertIn("<strong>Failure analysis:</strong> Zephyros config prompt not found", html)

    def test_build_html_uses_failure_report_when_status_has_no_failure_fields(self):
        with TemporaryDirectory() as tmp:
            report = Path(tmp) / "failure_report.log"
            report.write_text(
                "\n".join([
                    "==========================================",
                    "Zephyros Build Failure Report",
                    "==========================================",
                    "",
                    "[Failure analysis]",
                    "ninja: build stopped: subcommand failed.",
                    "",
                    "[Recent errors]",
                ]),
                encoding="utf-8",
            )
            status = Path(tmp) / "status.txt"
            status.write_text(
                "\n".join([
                    "[GDM7275X Zephyros]",
                    "Result       : FAIL",
                    f"Failure rpt  : {report}",
                ]),
                encoding="utf-8",
            )

            html = build_html(status, "[TestPy] Report", "20260515", r"K:\ENG\ENG05\CS_team\James")

        self.assertIn("<strong>Failure analysis:</strong> ninja: build stopped: subcommand failed.", html)


if __name__ == "__main__":
    unittest.main()
