import argparse
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from autobuild import ops


class OpsTests(unittest.TestCase):
    def test_show_config_prints_managed_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "autobuild_common.env"
            config.write_text(
                "\n".join([
                    "MAIL_TO='jamesahn@gctsemi.com'",
                    "REPORT_SUBJECT_PREFIX='[TestPy]'",
                    "SAMBA_UPLOAD_LOCAL_DIR='/tmp/james'",
                ]),
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                rc = ops.show_config(argparse.Namespace(config=str(config)))

        text = output.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("MAIL_TO=jamesahn@gctsemi.com", text)
        self.assertIn("REPORT_SUBJECT_PREFIX=[TestPy]", text)
        self.assertIn("SAMBA_UPLOAD_LOCAL_DIR=/tmp/james", text)

    def test_set_config_replaces_and_appends_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "autobuild_common.env"
            config.write_text(
                "\n".join([
                    "MAIL_TO='old@gctsemi.com'",
                    "REPORT_SUBJECT_PREFIX='[Old]'",
                ]) + "\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(
                config=str(config),
                mail_to="new@gctsemi.com",
                subject_prefix="[TestPy]",
                test_mail_to="test@gctsemi.com",
                test_subject_prefix=None,
                samba_local_dir=None,
                samba_unc_root=None,
                email_noti_enabled=None,
                set_values=["START_AFTER_MINUTES=2"],
                show_after=False,
            )

            rc = ops.set_config(args)

            text = config.read_text(encoding="utf-8")

        self.assertEqual(rc, 0)
        self.assertIn("MAIL_TO=new@gctsemi.com", text)
        self.assertIn("REPORT_SUBJECT_PREFIX='[TestPy]'", text)
        self.assertIn("TEST_MAIL_TO=test@gctsemi.com", text)
        self.assertIn("START_AFTER_MINUTES=2", text)

    def test_show_status_summarizes_status_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_file = root / "daily_autobuild_status_20260515.txt"
            status_file.write_text(
                "\n".join([
                    "[GDM7275X OpenWrt v1.00]",
                    "Result       : FAIL",
                    "Duration     : 00:10:00",
                    "Run ts       : 20260515_030000",
                    "Fail reason  : build failed",
                    "",
                    "[GDM7275X OpenWrt master]",
                    "Result       : SUCCESS",
                    "Duration     : 00:08:00",
                    "Run ts       : 20260515_030100",
                ]) + "\n",
                encoding="utf-8",
            )
            output = io.StringIO()
            args = argparse.Namespace(
                run_date="20260515",
                config=str(root / "autobuild_common.env"),
                status_file=str(status_file),
                raw=False,
            )
            with redirect_stdout(output):
                rc = ops.show_status(args)

        text = output.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("Summary    : FAIL=1, SUCCESS=1", text)
        self.assertIn("[GDM7275X OpenWrt v1.00] FAIL", text)
        self.assertIn("fail     : build failed", text)


if __name__ == "__main__":
    unittest.main()
