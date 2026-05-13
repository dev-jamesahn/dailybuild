from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from autobuild import upload


class UploadTests(unittest.TestCase):
    def test_upload_dir_name_matches_known_targets(self):
        self.assertEqual(
            upload.upload_dir_name("GDM7275X OpenWrt v1.00", openwrt_branch="v1.00"),
            "GDM7275X/openwrt_v100",
        )
        self.assertEqual(
            upload.upload_dir_name("GDM7275X Linuxos master", os_project_name="Linuxos"),
            "GDM7275X/linuxos_master",
        )
        self.assertEqual(
            upload.upload_dir_name("GDM7243ST uTKernel", os_project_name="uTKernel"),
            "GDM7243ST/uTKernel",
        )

    def test_upload_respects_existing_flag_without_force(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "state"
            state.mkdir()
            status_file = root / "daily_autobuild_status_20260513.txt"
            status_file.write_text("[GDM7275X OpenWrt v1.00]\n", encoding="utf-8")
            flag = state / ".daily_autobuild_logs_uploaded_20260513.flag"
            flag.write_text("uploaded_at=test\n", encoding="utf-8")
            output = root / "upload"
            config = root / "config.env"
            config.write_text(
                "\n".join([
                    "SAMBA_UPLOAD_ENABLED=1",
                    f"SAMBA_UPLOAD_LOCAL_DIR='{output}'",
                    f"AUTOBUILD_STATE_ROOT='{state}'",
                ]),
                encoding="utf-8",
            )

            rc = upload.run(SimpleNamespace(
                run_date="20260513",
                config=str(config),
                status_file=str(status_file),
                output_dir=None,
                upload_subdir=None,
                force=False,
            ))

        self.assertEqual(rc, 0)
        self.assertFalse((output / "20260513").exists())

    def test_upload_subdir_places_package_under_test_run_timestamp(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "state"
            state.mkdir()
            log_dir = root / "logs" / "linuxos" / "gdm7275x" / "20260513_145822"
            log_dir.mkdir(parents=True)
            (log_dir / "build.log").write_text("ok\n", encoding="utf-8")
            (log_dir / "summary.env").write_text(
                "\n".join([
                    "TARGET_NAME='GDM7275X Linuxos master'",
                    "OS_PROJECT_NAME=Linuxos",
                    "BUILD_RESULT=SUCCESS",
                ]),
                encoding="utf-8",
            )
            status_file = root / "one_time_daily_autobuild_status_20260513_145122.txt"
            status_file.write_text(
                "\n".join([
                    "[GDM7275X Linuxos master]",
                    "Result       : SUCCESS",
                    f"Log path     : {log_dir / 'build.log'}",
                ]),
                encoding="utf-8",
            )
            output = root / "upload"
            config = root / "config.env"
            config.write_text(
                "\n".join([
                    "SAMBA_UPLOAD_ENABLED=1",
                    f"SAMBA_UPLOAD_LOCAL_DIR='{output}'",
                    f"AUTOBUILD_STATE_ROOT='{state}'",
                ]),
                encoding="utf-8",
            )

            rc = upload.run(SimpleNamespace(
                run_date="20260513",
                config=str(config),
                status_file=str(status_file),
                output_dir=None,
                upload_subdir="Test/20260513_145122",
                force=False,
            ))

            self.assertEqual(rc, 0)
            self.assertTrue((output / "Test" / "20260513_145122" / "FW_build_info_20260513.txt").exists())
            self.assertTrue((output / "Test" / "20260513_145122" / "GDM7275X" / "linuxos_master" / "Log" / "build.log").exists())


if __name__ == "__main__":
    unittest.main()
