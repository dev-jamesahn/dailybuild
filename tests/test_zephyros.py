import tempfile
import unittest
from pathlib import Path

from autobuild.zephyros import ZephyrosBuild


class ZephyrosBuildTests(unittest.TestCase):
    def test_defaults_match_legacy_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "zephyros.env"
            config.write_text(
                "\n".join([
                    f"GCT_WORK_ROOT='{root / 'workspace'}'",
                    "PKG_VERSION=0.0.0",
                    "MODEL_LINEUP=GDM7275X",
                    "ZEPHYROS_CONFIG_SELECT=7",
                    "ZEPHYROS_CONFIG_NAME=gdm7259x_nsa",
                    "ZEPHYROS_REPO_URL=https://example.invalid/Zephyros",
                ]),
                encoding="utf-8",
            )

            build = ZephyrosBuild(config)

        self.assertEqual(build.target_name, "GDM7275X Zephyros")
        self.assertEqual(
            build.artifact_paths,
            "images/build/gdm7259x_nsa/zephyr/tk.gz images/build/gdm7259x_nsa/zephyr/zephyr.elf",
        )

    def test_dry_run_prints_native_runner_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "zephyros.env"
            config.write_text(
                "\n".join([
                    f"GCT_WORK_ROOT='{root / 'workspace'}'",
                    "ZEPHYROS_REPO_URL=https://example.invalid/Zephyros",
                ]),
                encoding="utf-8",
            )
            build = ZephyrosBuild(config)

            with unittest.mock.patch("sys.stdout.write") as write:
                rc = build.dry_run()

        self.assertEqual(rc, 0)
        rendered = "".join(call.args[0] for call in write.mock_calls if call.args)
        self.assertIn("native-python-zephyros-runner", rendered)
