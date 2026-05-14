import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from autobuild import runner


class RunnerTests(unittest.TestCase):
    def test_lock_dir_uses_config_stem_to_avoid_target_name_collisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "AUTOBUILD_TMP_ROOT": str(Path(tmp) / "tmp"),
                "TARGET_NAME": "GDM7275X",
                "MODEL_LINEUP": "GDM7275X",
            }
            openwrt_lock = runner._lock_dir(env, Path("openwrt_v1.00_autobuild.env"))
            linuxos_lock = runner._lock_dir(env, Path("gdm7275x_linuxos_master_autobuild.env"))

        self.assertNotEqual(openwrt_lock, linuxos_lock)
        self.assertEqual(openwrt_lock.name, "build_openwrt_v1.00_autobuild.lock")
        self.assertEqual(linuxos_lock.name, "build_gdm7275x_linuxos_master_autobuild.lock")

    def test_run_legacy_invokes_shell_wrapper_through_login_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "legacy"
            legacy.mkdir()
            script = legacy / "openwrt_autobuild.sh"
            script.write_text("#!/bin/bash\n", encoding="utf-8")
            script.chmod(0o755)
            config = root / "openwrt.env"
            config.write_text(
                "\n".join([
                    f"LEGACY_AUTOBUILD_DIR='{legacy}'",
                    f"AUTOBUILD_TMP_ROOT='{root / 'tmp'}'",
                ]),
                encoding="utf-8",
            )

            with mock.patch("autobuild.runner.subprocess.call", return_value=0) as call:
                rc = runner.run_openwrt(SimpleNamespace(config=str(config), dry_run=False))

        self.assertEqual(rc, 0)
        call.assert_called_once()
        self.assertEqual(call.call_args.args[0], ["/bin/bash", "-lc", str(script)])
        self.assertEqual(call.call_args.kwargs["env"]["CONFIG_FILE"], str(config))
