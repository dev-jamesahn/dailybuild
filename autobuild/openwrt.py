"""Native Python OpenWrt autobuild runner."""

from __future__ import annotations

import datetime as dt
import os
import re
import shutil
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .config import AutobuildPaths, daily_status_file, merged_env
from .gitinfo import last_commit
from .status import generate_daily_status
from .upload import safe_name


def _q(value: str | Path) -> str:
    return shlex.quote(str(value))


def _fmt_duration(seconds: int) -> str:
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _run_user() -> str:
    return os.environ.get("USER") or os.environ.get("LOGNAME") or subprocess.check_output(["id", "-un"], text=True).strip()


def _git(repo: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], text=True, capture_output=True)
    if check and proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"git {' '.join(args)} failed")
    return proc.stdout.strip()


def _write_env(path: Path, values: dict[str, str]) -> None:
    path.write_text("".join(f"{key}={shlex.quote(str(value))}\n" for key, value in values.items()), encoding="utf-8")


@dataclass
class RepoSpec:
    key: str
    display: str
    clone_dir: str
    url: str
    branch: str


@dataclass
class RepoState:
    repo: str
    branch: str
    commit: str
    path: Path


class TeeLogger:
    def __init__(self, build_log: Path):
        self._fp = build_log.open("a", encoding="utf-8", errors="replace")

    def close(self) -> None:
        self._fp.close()

    def write(self, text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()
        self._fp.write(text)
        self._fp.flush()

    def line(self, text: str = "") -> None:
        self.write(text + "\n")


class OpenWrtBuild:
    def __init__(self, config_file: str | Path):
        self.config_file = Path(config_file).expanduser()
        if not self.config_file.is_file():
            raise SystemExit(f"Missing config file: {self.config_file}")

        self.env = merged_env(self.config_file, {"CONFIG_FILE": str(self.config_file)})
        self.paths = AutobuildPaths.from_env(self.env)
        self.run_ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_date = dt.datetime.now().strftime("%Y%m%d")
        self.start_epoch = int(time.time())

        self.openwrt_branch = self.env.get("OPENWRT_BRANCH", "v1.00")
        self.pkg_version = self.env.get("PKG_VERSION", "0.0.0")
        self.branch_slug = safe_name(self.openwrt_branch)
        self.model_lineup = self.env.get("MODEL_LINEUP", "GDM7275X")
        self.openwrt_url = self.env.get("OPENWRT_SOURCE_REPO_URL", "https://release.gctsemi.com/openwrt")

        self.repo_storage_root = Path(self.env.get("AUTOBUILD_REPO_ROOT") or self.paths.autobuild_root / "repos").expanduser()
        self.clone_root = Path(self.env.get("CLONE_ROOT") or self.repo_storage_root / "openwrt/deps").expanduser()
        self.openwrt_dir = Path(self.env.get("OPENWRT_DIR") or self.repo_storage_root / f"openwrt/builds/{self.openwrt_branch}").expanduser()
        self.work_dir = Path(self.env.get("WORK_DIR") or self.paths.tmp_root / f"openwrt_{_run_user()}_{self.branch_slug}").expanduser()
        self.log_root = Path(self.env.get("LOG_ROOT") or self.paths.log_root / f"openwrt/{self.openwrt_branch}").expanduser()
        self.run_dir = self.log_root / self.run_ts
        self.build_log = self.run_dir / "build.log"
        self.verbose_log = self.run_dir / "build_verbose.log"
        self.hash_log = self.run_dir / "hashes.log"
        self.failure_report = self.run_dir / "failure_report.log"
        self.status_file = self.run_dir / "status.txt"
        self.summary_file = self.run_dir / "summary.env"
        self.latest_link = self.log_root / "latest"
        self.latest_status_file = self.log_root / "latest_status.txt"
        self.latest_summary_file = self.log_root / "latest_summary.env"
        self.daily_status = daily_status_file(self.env, self.run_date)
        self.artifact_root = Path(self.env.get("ARTIFACT_ROOT") or self.openwrt_dir).expanduser()
        self.artifact_paths = self.env.get("ARTIFACT_PATHS", "bin/targets/gdm7275x/generic/owrt*.*")

        self.current_stage = "init"
        self.build_result = "FAIL"
        self.fail_reason = ""
        self.failure_analysis = ""
        self.main_repo_commit = ""
        self.main_repo_meta = {"commit": "", "author": "", "date": "", "subject": ""}
        self.manifest_hashes: dict[str, str] = {}
        self.repo_states: dict[str, RepoState] = {}
        self.logger: TeeLogger | None = None

    @property
    def target_name(self) -> str:
        return f"{self.model_lineup} OpenWrt {self.openwrt_branch}"

    def run(self) -> int:
        self._prepare_dirs()
        self.logger = TeeLogger(self.build_log)
        rc = 1
        try:
            self._run_steps()
            self.build_result = "SUCCESS"
            rc = 0
        except Exception as exc:
            self.build_result = "FAIL"
            if not self.fail_reason:
                self.fail_reason = f"Command failed during stage: {self.current_stage}"
            self.logger.line(f"[ERROR] {exc}")
            rc = 1
        finally:
            self._finalize(rc)
            if self.logger:
                self.logger.close()
        return rc

    def dry_run(self) -> int:
        self._prepare_dirs()
        print(f"CONFIG_FILE={_q(self.config_file)}")
        print(f"OPENWRT_DIR={_q(self.openwrt_dir)}")
        print(f"RUN_DIR={_q(self.run_dir)}")
        print("native-python-openwrt-runner")
        return 0

    def _prepare_dirs(self) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.clone_root.mkdir(parents=True, exist_ok=True)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.paths.state_root.mkdir(parents=True, exist_ok=True)
        self.build_log.touch()

    def _run_steps(self) -> None:
        log = self.logger
        assert log is not None
        log.line(f"[INFO] OpenWrt {self.openwrt_branch} autobuild started")
        log.line(f"[INFO] Workspace root: {self.paths.work_root}")
        log.line(f"[INFO] Autobuild root: {self.paths.autobuild_root}")
        log.line(f"[INFO] Run directory : {self.run_dir}")
        log.line(f"[INFO] Config file    : {self.config_file}")
        log.line(f"[INFO] Model lineup   : {self.model_lineup}")
        log.line(f"[INFO] Work directory: {self.work_dir}")
        log.line(f"[INFO] Package ver   : {self.pkg_version}")
        log.line(f"[INFO] OpenWrt dir   : {self.openwrt_dir}")
        log.line(f"[INFO] OpenWrt repo  : {self.openwrt_url}")
        log.line(f"[INFO] Clone root    : {self.clone_root}")
        log.line(f"[INFO] Failure rpt  : {self.failure_report}")
        self.hash_log.write_text("", encoding="utf-8")

        for spec in self._repo_specs():
            self._ensure_repo_ready(spec)

        self.current_stage = "clone_openwrt"
        log.line()
        log.line("[OpenWrt clone]")
        log.line("------------------------------------------")
        if self.openwrt_dir.exists():
            shutil.rmtree(self.openwrt_dir)
        self._run_logged(["git", "clone", "-b", self.openwrt_branch, "--single-branch", self.openwrt_url, str(self.openwrt_dir)])
        self.main_repo_commit = _git(self.openwrt_dir, "rev-parse", "HEAD")
        self._append_hash("OPENWRT", self.openwrt_branch, self.main_repo_commit, self.openwrt_dir, self.openwrt_url)

        self.current_stage = "update_manifest"
        log.line()
        log.line("[Manifest update]")
        log.line("------------------------------------------")
        self._update_manifest()

        self.current_stage = "validate_branch"
        current_branch = _git(self.openwrt_dir, "rev-parse", "--abbrev-ref", "HEAD")
        if current_branch != self.openwrt_branch:
            self.fail_reason = f"OpenWrt current branch is {current_branch}, expected {self.openwrt_branch}"
            raise RuntimeError(self.fail_reason)

        self.current_stage = "build_openwrt"
        log.line()
        log.line("[OpenWrt build]")
        log.line("------------------------------------------")
        if not (self.openwrt_dir / "ext-toolchain.sh").is_file():
            self.fail_reason = f"ext-toolchain.sh not found: {self.openwrt_dir / 'ext-toolchain.sh'}"
            raise RuntimeError(self.fail_reason)
        self._run_ext_toolchain()
        self._run_make_with_retry()
        log.line()
        log.line(f"[INFO] OpenWrt {self.openwrt_branch} autobuild completed successfully")

    def _repo_specs(self) -> list[RepoSpec]:
        return [
            RepoSpec("GDM", self.env.get("GDM_SOURCE_DISPLAY", "linuxos master"), self.env.get("GDM_SOURCE_CLONE_DIR", "linuxos_autobuild"), self.env.get("GDM_SOURCE_REPO_URL", "https://release.gctsemi.com/linuxos"), self.env.get("GDM_SOURCE_BRANCH", "master")),
            RepoSpec("SBL", self.env.get("SBL_SOURCE_DISPLAY", "7275X SBL"), self.env.get("SBL_SOURCE_CLONE_DIR", "7275X_sbl_autobuild"), self.env.get("SBL_SOURCE_REPO_URL", "https://release.gctsemi.com/sbl/7275x"), self.env.get("SBL_SOURCE_BRANCH", "")),
            RepoSpec("UBOOT", self.env.get("UBOOT_SOURCE_DISPLAY", "7275X U-Boot"), self.env.get("UBOOT_SOURCE_CLONE_DIR", "7275X_uboot_autobuild"), self.env.get("UBOOT_SOURCE_REPO_URL", "https://release.gctsemi.com/u-boot/7275x"), self.env.get("UBOOT_SOURCE_BRANCH", "")),
        ]

    def _ensure_repo_ready(self, spec: RepoSpec) -> None:
        log = self.logger
        assert log is not None
        self.current_stage = f"sync_{spec.key.lower()}"
        repo_dir = self.clone_root / spec.clone_dir
        log.line()
        log.line(f"[{spec.display}]")
        log.line("------------------------------------------")

        if not (repo_dir / ".git").is_dir():
            log.line(f"[INFO] Clone missing repo into {repo_dir}")
            cmd = ["git", "clone"]
            if spec.branch:
                cmd.extend(["-b", spec.branch, "--single-branch"])
            cmd.extend([spec.url, str(repo_dir)])
            self._run_logged(cmd)
        else:
            current_url = _git(repo_dir, "config", "--get", "remote.origin.url", check=False)
            if current_url != spec.url:
                log.line(f"[INFO] Update origin URL: {repo_dir}")
                log.line(f"[INFO]   old: {current_url or 'none'}")
                log.line(f"[INFO]   new: {spec.url}")
                self._run_logged(["git", "-C", str(repo_dir), "remote", "set-url", "origin", spec.url])

        if spec.branch:
            self._run_logged(["git", "-C", str(repo_dir), "fetch", "origin", f"+refs/heads/{spec.branch}:refs/remotes/origin/{spec.branch}"])
            branch = f"origin/{spec.branch}"
            commit = _git(repo_dir, "rev-parse", branch)
        else:
            branch = _git(repo_dir, "rev-parse", "--abbrev-ref", "HEAD")
            self._run_logged(["git", "-C", str(repo_dir), "pull", "--ff-only", "origin", branch])
            commit = _git(repo_dir, "rev-parse", "HEAD")

        self.repo_states[spec.key] = RepoState(spec.url, branch, commit, repo_dir)
        self.manifest_hashes[spec.key] = commit
        self._append_hash(spec.key, branch, commit, repo_dir, spec.url)

    def _append_hash(self, key: str, branch: str, commit: str, repo_dir: Path, url: str) -> None:
        line = f"{key}|{branch}|{commit}|{repo_dir}|{url}"
        assert self.logger is not None
        self.logger.line(line)
        with self.hash_log.open("a", encoding="utf-8") as fp:
            fp.write(line + "\n")

    def _update_manifest(self) -> None:
        manifest = self.openwrt_dir / "include/manifest.mk"
        text = manifest.read_text(encoding="utf-8")
        replacements = {
            r"^GCT_PKG_VERSION:=.*$": f"GCT_PKG_VERSION:={self.pkg_version}",
            r"^GDM_REPO:=.*$": f"GDM_REPO:=\"{self.repo_states['GDM'].repo}\"",
            r"^GDM_COMMIT:=.*$": f"GDM_COMMIT:=\"{self.repo_states['GDM'].commit}\"",
            r"^SBL_REPO:=.*$": f"SBL_REPO:=\"{self.repo_states['SBL'].repo}\"",
            r"^SBL_COMMIT:=.*$": f"SBL_COMMIT:=\"{self.repo_states['SBL'].commit}\"",
            r"^UBOOT_REPO:=.*$": f"UBOOT_REPO:=\"{self.repo_states['UBOOT'].repo}\"",
            r"^UBOOT_COMMIT:=.*$": f"UBOOT_COMMIT:=\"{self.repo_states['UBOOT'].commit}\"",
        }
        for pattern, replacement in replacements.items():
            text = re.sub(pattern, replacement, text, flags=re.MULTILINE)
        manifest.write_text(text, encoding="utf-8")

    def _run_ext_toolchain(self) -> None:
        assert self.logger is not None
        proc = subprocess.Popen(
            ["bash", "./ext-toolchain.sh"],
            cwd=self.openwrt_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=self._subprocess_env(),
            bufsize=1,
        )
        if proc.stdin:
            proc.stdin.write("\n")
            proc.stdin.close()
        assert proc.stdout is not None
        for line in proc.stdout:
            self.logger.write(line)
        rc = proc.wait()
        if rc != 0:
            self.fail_reason = "ext-toolchain.sh failed"
            raise RuntimeError(self.fail_reason)
        self.logger.line()
        self.logger.line("===== EXT-TOOLCHAIN SUCCESS =====")

    def _run_make_with_retry(self) -> None:
        rc = self._run_logged(["make"], cwd=self.openwrt_dir, check=False)
        if rc == 0:
            self.logger and self.logger.line("\n===== OPENWRT DIRTY BUILD SUCCESS =====")
            return
        self.logger and self.logger.line("\n===== OPENWRT DIRTY BUILD FAIL =====")
        with self.verbose_log.open("a", encoding="utf-8", errors="replace") as verbose:
            rc = self._run_logged(["make", "V=sc"], cwd=self.openwrt_dir, check=False, extra_fp=verbose, preface="===== RETRY WITH V=sc =====\n")
        if rc == 0:
            self.logger and self.logger.line("\n===== OPENWRT DIRTY BUILD SUCCESS (V=sc) =====")
            return
        self.logger and self.logger.line("\n===== OPENWRT DIRTY BUILD FAIL (V=sc) =====")
        raise RuntimeError("OpenWrt build failed")

    def _run_logged(self, cmd: list[str], cwd: Path | None = None, check: bool = True, extra_fp=None, preface: str = "") -> int:
        assert self.logger is not None
        if preface:
            self.logger.write(preface)
            if extra_fp:
                extra_fp.write(preface)
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=self._subprocess_env(),
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            self.logger.write(line)
            if extra_fp:
                extra_fp.write(line)
                extra_fp.flush()
        rc = proc.wait()
        if check and rc != 0:
            raise RuntimeError(f"Command failed: {' '.join(shlex.quote(part) for part in cmd)}")
        return rc

    def _subprocess_env(self) -> dict[str, str]:
        # Keep config values out of the build environment. In particular,
        # PKG_VERSION is only for include/manifest.mk and must not override
        # package Makefile version calculations inside OpenWrt.
        return dict(os.environ)

    def _finalize(self, rc: int) -> None:
        end_epoch = int(time.time())
        duration = end_epoch - self.start_epoch
        started = dt.datetime.fromtimestamp(self.start_epoch).strftime("%Y-%m-%d %H:%M:%S")
        ended = dt.datetime.fromtimestamp(end_epoch).strftime("%Y-%m-%d %H:%M:%S")
        if rc == 0:
            self.build_result = "SUCCESS"
        else:
            self.build_result = "FAIL"
            if not self.fail_reason:
                self.fail_reason = f"Command failed during stage: {self.current_stage}"
            self._analyze_failure()
            if not self.failure_analysis:
                self.failure_analysis = self.fail_reason

        if (self.openwrt_dir / ".git").is_dir():
            try:
                self.main_repo_meta = last_commit(self.openwrt_dir)
            except Exception:
                self.main_repo_meta = {"commit": self.main_repo_commit, "author": "", "date": "", "subject": ""}

        summary = {
            "TARGET_NAME": self.target_name,
            "RUN_TS": self.run_ts,
            "OPENWRT_BRANCH": self.openwrt_branch,
            "MODEL_LINEUP": self.model_lineup,
            "OPENWRT_SOURCE_REPO_URL": self.openwrt_url,
            "PKG_VERSION": self.pkg_version,
            "BUILD_RESULT": self.build_result,
            "CURRENT_STAGE": self.current_stage,
            "BUILD_STARTED_AT": started,
            "BUILD_ENDED_AT": ended,
            "BUILD_DURATION_SEC": str(duration),
            "BUILD_DURATION_FMT": _fmt_duration(duration),
            "BUILD_LOG": str(self.build_log),
            "VERBOSE_LOG": str(self.verbose_log),
            "HASH_LOG": str(self.hash_log),
            "FAILURE_REPORT": str(self.failure_report),
            "ARTIFACT_ROOT": str(self.artifact_root),
            "ARTIFACT_PATHS": self.artifact_paths,
            "FAIL_REASON": self.fail_reason,
            "FAILURE_ANALYSIS": self.failure_analysis,
            "MAIN_REPO_URL": self.openwrt_url,
            "MAIN_REPO_DIR": str(self.openwrt_dir),
            "MAIN_REPO_COMMIT": self.main_repo_commit,
            "MAIN_REPO_LAST_COMMIT": self.main_repo_meta.get("commit", ""),
            "MAIN_REPO_LAST_AUTHOR": self.main_repo_meta.get("author", ""),
            "MAIN_REPO_LAST_DATE": self.main_repo_meta.get("date", ""),
            "MAIN_REPO_LAST_SUBJECT": self.main_repo_meta.get("subject", ""),
            "MANIFEST_GDM_COMMIT": self.manifest_hashes.get("GDM", ""),
            "MANIFEST_SBL_COMMIT": self.manifest_hashes.get("SBL", ""),
            "MANIFEST_UBOOT_COMMIT": self.manifest_hashes.get("UBOOT", ""),
        }
        _write_env(self.summary_file, summary)
        self._write_status(started, ended, _fmt_duration(duration))
        self._update_latest_links()
        self._update_daily_status()

    def _write_status(self, started: str, ended: str, duration: str) -> None:
        lines = [
            "==========================================",
            f"Build result : {self.build_result}",
            f"Current stage: {self.current_stage}",
            f"Build started: {started}",
            f"Build ended  : {ended}",
            f"Duration     : {duration}",
            f"Log path     : {self.build_log}",
            f"Verbose log  : {self.verbose_log}",
            f"Hash log     : {self.hash_log}",
            f"Failure rpt  : {self.failure_report}",
            f"Artifact root: {self.artifact_root}",
            f"Artifacts    : {self.artifact_paths}",
        ]
        if self.fail_reason:
            lines.append(f"Fail reason  : {self.fail_reason}")
        if self.failure_analysis:
            lines.append(f"Failure analysis: {self.failure_analysis}")
        text = "\n".join(lines) + "\n"
        self.status_file.write_text(text, encoding="utf-8")
        if self.logger:
            self.logger.write(text)

    def _update_latest_links(self) -> None:
        if self.latest_link.exists() or self.latest_link.is_symlink():
            self.latest_link.unlink()
        self.latest_link.symlink_to(self.run_dir)
        shutil.copy2(self.status_file, self.latest_status_file)
        shutil.copy2(self.summary_file, self.latest_summary_file)

    def _update_daily_status(self) -> None:
        self.daily_status.parent.mkdir(parents=True, exist_ok=True)
        self.daily_status.write_text(generate_daily_status(self.paths.log_root), encoding="utf-8")
        if self.logger:
            self.logger.line(f"[INFO] Latest run link : {self.latest_link}")
            self.logger.line(f"[INFO] Latest status   : {self.latest_status_file}")
            self.logger.line(f"[INFO] Daily status    : {self.daily_status}")

    def _analyze_failure(self) -> None:
        source_log = self.verbose_log if self.verbose_log.exists() and self.verbose_log.stat().st_size else self.build_log
        text = source_log.read_text(encoding="utf-8", errors="replace") if source_log.exists() else ""
        self.failure_analysis = self._extract_failure_analysis(text)
        report = [
            "==========================================",
            "OpenWrt Build Failure Report",
            "==========================================",
            f"Repo path      : {self.openwrt_dir}",
            f"Build log      : {self.build_log}",
            f"Verbose log    : {self.verbose_log}",
            f"Hash log       : {self.hash_log}",
            f"Source log     : {source_log}",
            f"Generated at   : {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Current stage  : {self.current_stage}",
            f"Fail reason    : {self.fail_reason}",
        ]
        if self.failure_analysis:
            report.extend(["", "[Failure analysis]", self.failure_analysis])
        report.extend(["", "[Recent errors]"])
        error_re = re.compile(r"fatal error:|error:|No such file or directory|cannot find|undefined reference|\*\*\* .*Error|make(\[[0-9]+\])?: \*\*\*")
        report.extend([line for line in text.splitlines() if error_re.search(line)][-40:])
        self.failure_report.write_text("\n".join(report) + "\n", encoding="utf-8")

    def _extract_failure_analysis(self, text: str) -> str:
        make_lines = [line for line in text.splitlines() if re.search(r"make(\[[0-9]+\])?: \*\*\* \[[^]]+\] Error [0-9]+", line)]
        final = ""
        for line in make_lines:
            if str(self.openwrt_dir) in line and not re.search(r"include/toplevel\.mk|target/Makefile|package/Makefile|tools/Makefile|Error [0-9]+ \(ignored\)", line):
                final = line
        if not final:
            for line in make_lines:
                if not re.search(r"include/toplevel\.mk|target/Makefile|package/Makefile|tools/Makefile|Error [0-9]+ \(ignored\)", line):
                    final = line
        if not final and make_lines:
            final = make_lines[-1]

        package_errors = [re.sub(r"\x1B\[[0-9;]*[mK]", "", line).strip() for line in text.splitlines() if "ERROR: package/" in line and "failed to build" in line]
        if final:
            location = ""
            match = re.search(r"\[[^]]*: ([^]]+)\] Error [0-9]+", final)
            if match:
                location = match.group(1)
            repo_hint = ""
            rel = location.replace(str(self.openwrt_dir) + "/", "")
            if rel.startswith("build_dir/") and "/image-" in rel:
                repo_hint = " (likely source: OpenWrt target)"
            return f"{final}{' at ' + location if location else ''}{repo_hint}"
        if package_errors:
            return package_errors[-1]
        root_errors = [
            line for line in text.splitlines()
            if re.search(r"fatal error:|\s+error:|undefined reference|cannot find|No such file or directory", line)
            and "comment at start of rule is unportable" not in line
        ]
        return root_errors[-1] if root_errors else ""


def run(args) -> int:
    build = OpenWrtBuild(args.config)
    if getattr(args, "dry_run", False):
        return build.dry_run()
    return build.run()
