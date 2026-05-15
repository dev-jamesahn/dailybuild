import argparse
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from core import logtail


class LogtailTests(unittest.TestCase):
    def test_no_follow_prints_prefixed_existing_and_waiting_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "logs/openwrt/v1.00/cron_runner.log"
            log.parent.mkdir(parents=True)
            log.write_text("first\nsecond\nthird\n", encoding="utf-8")
            config = root / "dailybuild_common.env"
            config.write_text(
                f"DAILYBUILD_LOG_ROOT={root / 'logs'}\n"
                f"DAILYBUILD_STATE_ROOT={root / 'state'}\n"
                f"GCT_WORK_ROOT={root}\n",
                encoding="utf-8",
            )

            args = argparse.Namespace(config=str(config), lines=2, interval=0.2, no_follow=True)
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(logtail.tail_logs(args), 0)

        text = output.getvalue()
        self.assertIn("[openwrt-v1.00] second", text)
        self.assertIn("[openwrt-v1.00] third", text)
        self.assertIn("[openwrt-master] [waiting]", text)
