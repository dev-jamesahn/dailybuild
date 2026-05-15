import argparse
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from core import scheduler


class SchedulerTests(unittest.TestCase):
    def test_list_jobs_reports_daily_one_time_and_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "dailybuild_common.env"
            state_root = root / "state"
            log_root = root / "logs"
            state_root.mkdir()
            log_root.mkdir()
            config.write_text(
                "\n".join([
                    f"GCT_WORK_ROOT='{root}'",
                    f"DAILYBUILD_ROOT='{root}'",
                    f"DAILYBUILD_LOG_ROOT='{log_root}'",
                    f"DAILYBUILD_STATE_ROOT='{state_root}'",
                ]),
                encoding="utf-8",
            )

            status_file = state_root / "one_time_dailybuild_status_20260515_031500.txt"
            status_file.write_text("[GDM7275X OpenWrt v1.00]\nResult       : SUCCESS\n", encoding="utf-8")
            (state_root / ".one_time_dailybuild_mail_sent_20260515_031500.flag").write_text("ok\n", encoding="utf-8")

            ps_output = "\n".join([
                "1234 /usr/bin/python3 /home/jamesahn/gct-build-tools/dailybuild/dailybuild.py run-openwrt --config x",
                "2222 /usr/bin/python3 /home/jamesahn/gct-build-tools/dailybuild/dailybuild.py notify --config y",
            ]) + "\n"

            args = argparse.Namespace(config=str(config))
            output = io.StringIO()
            with mock.patch("core.scheduler._running_dailybuild_processes", return_value=scheduler._parse_ps_output(ps_output)):
                with redirect_stdout(output):
                    rc = scheduler.list_jobs(args)

        text = output.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("Daily Cron Jobs", text)
        self.assertIn("One-Time Tests", text)
        self.assertIn("Running Processes", text)
        self.assertIn("20260515_031500", text)
        self.assertIn("state=pending", text)
        self.assertIn("sent=yes", text)
        self.assertIn("uploaded=no", text)
        self.assertIn("run-openwrt", text)
        self.assertIn("notify", text)

    def test_parse_ps_output_keeps_only_dailybuild_entrypoint(self):
        text = "\n".join([
            "1000 python something_else.py",
            "1001 /usr/bin/python3 /home/jamesahn/gct-build-tools/dailybuild/dailybuild.py run-os --config a",
        ])
        rows = scheduler._parse_ps_output(text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["pid"], "1001")
        self.assertIn("run-os", rows[0]["cmd"])


if __name__ == "__main__":
    unittest.main()
