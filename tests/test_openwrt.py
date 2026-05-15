import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.openwrt import OpenWrtBuild


class OpenWrtBuildTests(unittest.TestCase):
    def test_subprocess_env_does_not_export_config_pkg_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "openwrt.env"
            config.write_text(
                "\n".join([
                    f"DAILYBUILD_ROOT='{root / 'dailybuild'}'",
                    "OPENWRT_BRANCH=master",
                    "PKG_VERSION=0.0.0",
                ]),
                encoding="utf-8",
            )

            with mock.patch.dict("os.environ", {}, clear=True):
                build = OpenWrtBuild(config)
                env = build._subprocess_env()

        self.assertNotIn("PKG_VERSION", env)

    def test_failure_analysis_prefers_final_build_artifact_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "openwrt.env"
            config.write_text(f"DAILYBUILD_ROOT='{root / 'dailybuild'}'\n", encoding="utf-8")
            build = OpenWrtBuild(config)
            build.openwrt_dir = root / "dailybuild/repos/openwrt/builds/v1.00"
            log = "\n".join([
                "Makefile.am:282: error: '#' comment at start of rule is unportable",
                f"make[5]: *** [Makefile:165: {build.openwrt_dir}/build_dir/target/image-gdm7275x-airspan.dtb] Error 1",
                f"make[2]: *** [target/Makefile:30: target/linux/install] Error 1",
            ])

            analysis = build._extract_failure_analysis(log)

        self.assertIn("image-gdm7275x-airspan.dtb", analysis)
        self.assertNotIn("comment at start of rule", analysis)


if __name__ == "__main__":
    unittest.main()
