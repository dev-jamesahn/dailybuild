import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from autobuild import scheduler


class SchedulerTests(unittest.TestCase):
    def test_test_once_plan_expires_after_configured_runtime(self):
        old_env = os.environ.copy()
        try:
            with TemporaryDirectory() as tmp:
                root = Path(tmp)
                config_root = root / "config"
                config_root.mkdir()
                (config_root / "autobuild_common.env").write_text(
                    "\n".join([
                        f"AUTOBUILD_ROOT='{root / 'work'}'",
                        f"AUTOBUILD_LOG_ROOT='{root / 'work' / 'logs'}'",
                        f"AUTOBUILD_TMP_ROOT='{root / 'work' / 'tmp'}'",
                        f"AUTOBUILD_STATE_ROOT='{root / 'work' / 'state'}'",
                        "TEST_RUN_TS=20260513_145122",
                        "START_AFTER_MINUTES=1",
                        "NOTIFIER_START_AFTER_MINUTES=2",
                        "NOTIFIER_INTERVAL_MINUTES=10",
                        "NOTIFIER_REPEAT_COUNT=72",
                        "TEST_ONCE_MAX_RUNTIME_MINUTES=30",
                    ]),
                    encoding="utf-8",
                )
                os.environ.clear()
                os.environ.update(old_env)
                os.environ["AUTOBUILD_CONFIG_ROOT"] = str(config_root)

                commands, _ = scheduler._test_once_plan()

            notifier_commands = [item for item in commands if item.label.startswith("Daily notifier")]
            self.assertEqual([item.offset_minutes for item in notifier_commands], [2, 12, 22])
            self.assertTrue(all("One-time daily test expired: 20260513_145122" in item.command for item in commands))
            self.assertTrue(all("SAMBA_UPLOAD_SUBDIR=Test/20260513_145122" in item.command for item in notifier_commands))
        finally:
            os.environ.clear()
            os.environ.update(old_env)


if __name__ == "__main__":
    unittest.main()
