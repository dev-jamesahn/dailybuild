"""Daily log packaging and upload."""

from __future__ import annotations

import datetime as dt
import glob
import re
import shutil
import tempfile
from pathlib import Path

from .config import daily_status_file, merged_env, today
from .status import generate_fw_build_info


def safe_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")
    return safe or "unknown"


def upload_dir_name(target_name: str, openwrt_branch: str = "", os_project_name: str = "", os_build_variant: str = "", zephyros_config_name: str = "") -> str:
    if openwrt_branch:
        if openwrt_branch == "v1.00":
            return "GDM7275X/openwrt_v100"
        if openwrt_branch == "master":
            return "GDM7275X/openwrt_master"
        return f"GDM7275X/openwrt_{safe_name(openwrt_branch)}"
    if zephyros_config_name or target_name == "GDM7275X Zephyros":
        return "GDM7275X/Zephyros"
    if os_project_name == "Linuxos":
        return "GDM7275X/linuxos_master"
    if os_project_name == "uTKernel":
        lowered = target_name.lower()
        if "gdm7243st" in lowered:
            return "GDM7243ST/uTKernel"
        if "gdm7243a" in lowered:
            return "GDM7243A/uTKernel"
    if os_project_name == "zephyr-v2.3":
        return "GDM7243i/zephyr_v2.3" if "gdm7243i" in target_name.lower() else safe_name(target_name)
    return safe_name(target_name)


def _read_summary(summary_file: Path) -> dict[str, str]:
    from .config import load_env_file

    return load_env_file(summary_file)


def _copy_artifact(path: Path, target_dir: Path, manifest: list[str]) -> None:
    if path.is_dir():
        for child in sorted(p for p in path.rglob("*") if p.is_file()):
            shutil.copy2(child, target_dir / child.name)
            manifest.append(f"  {child} -> Image/{child.name}")
    elif path.is_file():
        shutil.copy2(path, target_dir / path.name)
        manifest.append(f"  {path} -> Image/{path.name}")


def _artifact_specs(summary: dict[str, str]) -> list[str]:
    explicit = summary.get("ARTIFACT_PATHS", "").split()
    if explicit:
        return explicit
    if summary.get("OPENWRT_BRANCH"):
        return ["bin/targets/gdm7275x/generic/owrt*.*"]
    if summary.get("OS_PROJECT_NAME") == "Linuxos":
        return ["images/*"]
    if summary.get("OS_PROJECT_NAME") == "uTKernel":
        return ["tk.gz", "disa"]
    if summary.get("OS_PROJECT_NAME") == "zephyr-v2.3" and summary.get("OS_BUILD_VARIANT"):
        variant = summary["OS_BUILD_VARIANT"]
        return [f"images/build/{variant}/zephyr/zephyr.bin", f"images/build/{variant}/zephyr/zephyr.elf"]
    if summary.get("ZEPHYROS_CONFIG_NAME"):
        name = summary["ZEPHYROS_CONFIG_NAME"]
        return [f"images/build/{name}/zephyr/tk.gz", f"images/build/{name}/zephyr/zephyr.elf"]
    return []


def _copy_artifacts(log_dir: Path, package_dir: Path, manifest: list[str]) -> None:
    summary_file = log_dir / "summary.env"
    if not summary_file.exists():
        return
    summary = _read_summary(summary_file)
    if summary.get("BUILD_RESULT") != "SUCCESS":
        return
    artifact_root = summary.get("ARTIFACT_ROOT") or summary.get("MAIN_REPO_DIR")
    specs = _artifact_specs(summary)
    if not artifact_root or not specs:
        return

    target_dir = package_dir / upload_dir_name(
        summary.get("TARGET_NAME", log_dir.name),
        summary.get("OPENWRT_BRANCH", ""),
        summary.get("OS_PROJECT_NAME", ""),
        summary.get("OS_BUILD_VARIANT", ""),
        summary.get("ZEPHYROS_CONFIG_NAME", ""),
    ) / "Image"
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest.extend(["", f"[{summary.get('TARGET_NAME', log_dir.name)} artifacts]", f"artifact_root={artifact_root}"])

    for spec in specs:
        matches = [Path(p) for p in glob.glob(str(Path(artifact_root) / spec))]
        if not matches and (Path(artifact_root) / spec).exists():
            matches = [Path(artifact_root) / spec]
        if not matches:
            manifest.append(f"  [missing] {Path(artifact_root) / spec}")
        for path in sorted(matches):
            _copy_artifact(path, target_dir, manifest)


def _status_log_paths(status_file: Path) -> list[Path]:
    paths = []
    for line in status_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("Log path") and ":" in line:
            paths.append(Path(line.split(":", 1)[1].strip()))
    return paths


def run(args) -> int:
    run_date = args.run_date or today()
    overrides = {"RUN_DATE": run_date}
    if getattr(args, "status_file", None):
        overrides["DAILY_STATUS_FILE"] = args.status_file
    if getattr(args, "output_dir", None):
        overrides["SAMBA_UPLOAD_LOCAL_DIR"] = args.output_dir
    env = merged_env(args.config, overrides)
    if env.get("SAMBA_UPLOAD_ENABLED", "1") != "1":
        print(f"[INFO] Daily log upload skipped: SAMBA_UPLOAD_ENABLED={env.get('SAMBA_UPLOAD_ENABLED')}")
        return 0

    status_file = daily_status_file(env, run_date)
    if not status_file.exists():
        print(f"[WARN] Daily log upload skipped: daily status file not found: {status_file}")
        return 0

    flag = Path(env.get("UPLOAD_FLAG_FILE") or Path(env.get("AUTOBUILD_STATE_ROOT", "/home/jamesahn/gct_workspace/autobuild/state")) / f".daily_autobuild_logs_uploaded_{run_date}.flag")
    if flag.exists() and not getattr(args, "force", False):
        print(f"[INFO] Daily log upload skipped: already uploaded for RUN_DATE={run_date}")
        return 0

    upload_root = env.get("SAMBA_UPLOAD_LOCAL_DIR")
    if not upload_root:
        raise SystemExit("SAMBA_UPLOAD_LOCAL_DIR is required in the Python uploader for now")

    with tempfile.TemporaryDirectory(prefix="daily_autobuild_upload.") as tmp:
        package_dir = Path(tmp) / run_date
        package_dir.mkdir(parents=True)
        manifest = [
            f"run_date={run_date}",
            f"generated_at={dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"daily_status_file={status_file}",
            "",
            "[uploaded_log_dirs]",
        ]

        (package_dir / f"FW_build_info_{run_date}.txt").write_text(generate_fw_build_info(status_file), encoding="utf-8")
        for log_file in _status_log_paths(status_file):
            log_dir = log_file.parent
            if not log_dir.is_dir():
                manifest.append(f"[WARN] Daily log upload: log dir not found: {log_dir}")
                continue
            summary = _read_summary(log_dir / "summary.env") if (log_dir / "summary.env").exists() else {}
            rel_dir = Path(upload_dir_name(
                summary.get("TARGET_NAME", log_dir.name),
                summary.get("OPENWRT_BRANCH", ""),
                summary.get("OS_PROJECT_NAME", ""),
                summary.get("OS_BUILD_VARIANT", ""),
                summary.get("ZEPHYROS_CONFIG_NAME", ""),
            )) / "Log"
            shutil.copytree(log_dir, package_dir / rel_dir, dirs_exist_ok=True)
            manifest.append(f"{log_dir} -> {rel_dir}")
            _copy_artifacts(log_dir, package_dir, manifest)

        (package_dir / "upload_manifest.txt").write_text("\n".join(manifest) + "\n", encoding="utf-8")
        target_dir = Path(upload_root) / run_date
        shutil.copytree(package_dir, target_dir, dirs_exist_ok=True)

    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text(f"uploaded_at={dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\nrun_date={run_date}\ntarget={target_dir}\n", encoding="utf-8")
    print(f"[INFO] Daily log upload completed: {target_dir}")
    return 0
