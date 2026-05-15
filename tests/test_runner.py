import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from core import runner


class RunnerTests(unittest.TestCase):
    def test_lock_dir_uses_config_stem_to_avoid_target_name_collisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "DAILYBUILD_TMP_ROOT": str(Path(tmp) / "tmp"),
                "TARGET_NAME": "GDM7275X",
                "MODEL_LINEUP": "GDM7275X",
            }
            openwrt_lock = runner._lock_dir(env, Path("openwrt_v1.00_dailybuild.env"))
            linuxos_lock = runner._lock_dir(env, Path("gdm7275x_linuxos_master_dailybuild.env"))

        self.assertNotEqual(openwrt_lock, linuxos_lock)
        self.assertEqual(openwrt_lock.name, "build_openwrt_v1.00_dailybuild.lock")
        self.assertEqual(linuxos_lock.name, "build_gdm7275x_linuxos_master_dailybuild.lock")

    def test_run_zephyros_delegates_to_native_runner(self):
        with mock.patch("core.runner.zephyros.run", return_value=0) as run:
            args = SimpleNamespace(config="/tmp/zephyros.env", dry_run=False)
            rc = runner.run_zephyros(args)

        self.assertEqual(rc, 0)
        run.assert_called_once_with(args)
