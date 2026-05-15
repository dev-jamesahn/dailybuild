import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dailybuild.osbuild import OSBuild, _EXPECT_CONFIG_SCRIPT


class OSBuildTests(unittest.TestCase):
    def test_subprocess_env_applies_toolchain_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "os.env"
            config.write_text(
                "\n".join([
                    f"DAILYBUILD_ROOT='{root / 'dailybuild'}'",
                    "MODEL_LINEUP=GDM7243A",
                    "OS_PROJECT_NAME=uTKernel",
                    "OS_REPO_URL=https://example.invalid/uTKernel",
                    "OS_PATH_PREPEND=/opt/toolchain/bin",
                    "OS_LD_LIBRARY_PATH_PREPEND=/opt/toolchain/lib",
                ]),
                encoding="utf-8",
            )

            with mock.patch.dict("os.environ", {"PATH": "/usr/bin", "LD_LIBRARY_PATH": "/usr/lib"}, clear=True):
                build = OSBuild(config)
                env = build._subprocess_env()

        self.assertEqual(env["PATH"], "/opt/toolchain/bin:/usr/bin")
        self.assertEqual(env["LD_LIBRARY_PATH"], "/opt/toolchain/lib:/usr/lib")

    def test_default_artifact_paths_for_zephyr_variant(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "os.env"
            config.write_text(
                "\n".join([
                    f"DAILYBUILD_ROOT='{root / 'dailybuild'}'",
                    "MODEL_LINEUP=GDM7243i",
                    "OS_PROJECT_NAME=zephyr-v2.3",
                    "OS_REPO_URL=https://example.invalid/zephyr",
                    "OS_BUILD_VARIANT=gdm7243i_nbiot_ntn_quad",
                ]),
                encoding="utf-8",
            )

            build = OSBuild(config)

        self.assertIn("images/build/gdm7243i_nbiot_ntn_quad/zephyr/zephyr.bin", build.artifact_paths)
        self.assertIn("zephyr_v2_3/gdm7243i", str(build.log_root))

    def test_expect_default_prompt_does_not_match_choice_brackets(self):
        self.assertIn(r"choice\[[0-9\-?]+\]:\s*$", _EXPECT_CONFIG_SCRIPT)
        self.assertIn(r"\([A-Za-z0-9_]+\)\s+\[[^]]+\]\s*$", _EXPECT_CONFIG_SCRIPT)
        self.assertNotIn(r"{\[[^]]+\]\s*$}", _EXPECT_CONFIG_SCRIPT)


if __name__ == "__main__":
    unittest.main()
