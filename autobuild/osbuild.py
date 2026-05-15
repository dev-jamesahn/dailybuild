"""Native Python OS/uTKernel/zephyr-v2.3 autobuild runner."""

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


def _run_user() -> str:
    return os.environ.get("USER") or os.environ.get("LOGNAME") or subprocess.check_output(["id", "-un"], text=True).strip()


def _fmt_duration(seconds: int) -> str:
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def _git(repo: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], text=True, capture_output=True)
    if check and proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"git {' '.join(args)} failed")
    return proc.stdout.strip()


def _write_env(path: Path, values: dict[str, str]) -> None:
    path.write_text("".join(f"{key}={shlex.quote(str(value))}\n" for key, value in values.items()), encoding="utf-8")


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


@dataclass
class Slugs:
    model: str
    project: str


class OSBuild:
    def __init__(self, config_file: str | Path):
        self.config_file = Path(config_file).expanduser()
        if not self.config_file.is_file():
            raise SystemExit(f"Missing config file: {self.config_file}")

        self.env = merged_env(self.config_file, {"CONFIG_FILE": str(self.config_file)})
        self.paths = AutobuildPaths.from_env(self.env)
        self.run_ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_date = dt.datetime.now().strftime("%Y%m%d")
        self.start_epoch = int(time.time())

        self.model_lineup = self._required("MODEL_LINEUP")
        self.project_name = self._required("OS_PROJECT_NAME")
        self.repo_url = self._required("OS_REPO_URL")
        self.repo_branch = self.env.get("OS_REPO_BRANCH", "")
        self.product_config = self.env.get("OS_PRODUCT_CONFIG", "")
        self.build_variant = self.env.get("OS_BUILD_VARIANT", "")
        self.config_cmd = self.env.get("OS_CONFIG_CMD", "")
        self.config_expect_choices = self.env.get("OS_CONFIG_EXPECT_CHOICES", "")
        self.build_cmd = self.env.get("OS_BUILD_CMD", "make")
        self.required_commands = self.env.get("OS_REQUIRED_COMMANDS", "git")
        self.path_prepend = self.env.get("OS_PATH_PREPEND", "")
        self.ld_library_path_prepend = self.env.get("OS_LD_LIBRARY_PATH_PREPEND", "")
        self.os_target_name = self.env.get("OS_TARGET_NAME", "")

        self.slugs = self._slugs()
        self.repo_storage_root = Path(self.env.get("AUTOBUILD_REPO_ROOT") or self.paths.autobuild_root / "repos").expanduser()
        self.work_dir = Path(self.env.get("WORK_DIR") or self.paths.tmp_root / f"{self.slugs.project}_{_run_user()}_{self.slugs.model}").expanduser()
        self.repo_dir = Path(self.env.get("REPO_DIR") or self.repo_storage_root / self.slugs.project / self.slugs.model).expanduser()
        self.log_root = Path(self.env.get("LOG_ROOT") or self.paths.log_root / self.slugs.project / self.slugs.model).expanduser()
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
        self.artifact_root = Path(self.env.get("ARTIFACT_ROOT") or self.repo_dir).expanduser()
        self.artifact_paths = self.env.get("ARTIFACT_PATHS", "") or self._default_artifact_paths()

        self.current_stage = "init"
        self.build_result = "FAIL"
        self.fail_reason = ""
        self.failure_analysis = ""
        self.main_repo_commit = ""
        self.main_repo_meta = {"commit": "", "author": "", "date": "", "subject": ""}
        self.logger: TeeLogger | None = None

    @property
    def target_name(self) -> str:
        if self.os_target_name:
            return self.os_target_name
        target = f"{self.model_lineup} {self.project_name}"
        if self.build_variant:
            target += f" - {self.build_variant}"
        return target

    def _required(self, key: str) -> str:
        value = self.env.get(key, "")
        if not value:
            raise SystemExit(f"{key} is required")
        return value

    def _slugs(self) -> Slugs:
        model = re.sub(r"[^A-Za-z0-9]+", "_", self.model_lineup).strip("_").lower() or "unknown"
        if self.project_name == "uTKernel":
            project = "uTKernel"
        else:
            project = re.sub(r"[^A-Za-z0-9]+", "_", self.project_name).strip("_").lower() or "unknown"
        return Slugs(model=model, project=project)

    def _default_artifact_paths(self) -> str:
        if self.project_name == "Linuxos":
            return "images/*"
        if self.project_name == "uTKernel":
            return "tk.gz disa"
        if self.project_name == "zephyr-v2.3":
            return f"images/build/{self.build_variant}/zephyr/zephyr.bin images/build/{self.build_variant}/zephyr/zephyr.elf"
        return ""

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
        print(f"CONFIG_FILE={self.config_file}")
        print(f"REPO_DIR={self.repo_dir}")
        print(f"RUN_DIR={self.run_dir}")
        print("native-python-os-runner")
        return 0

    def _prepare_dirs(self) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.paths.state_root.mkdir(parents=True, exist_ok=True)
        self.build_log.touch()

    def _run_steps(self) -> None:
        log = self.logger
        assert log is not None
        log.line(f"[INFO] {self.target_name} autobuild started")
        log.line(f"[INFO] Workspace root: {self.paths.work_root}")
        log.line(f"[INFO] Autobuild root: {self.paths.autobuild_root}")
        log.line(f"[INFO] Run directory : {self.run_dir}")
        log.line(f"[INFO] Config file   : {self.config_file}")
        log.line(f"[INFO] Model lineup  : {self.model_lineup}")
        log.line(f"[INFO] OS project    : {self.project_name}")
        log.line(f"[INFO] Repo URL      : {self.repo_url}")
        log.line(f"[INFO] Repo branch   : {self.repo_branch or 'default'}")
        log.line(f"[INFO] Product config: {self.product_config or 'none'}")
        log.line(f"[INFO] Build variant : {self.build_variant or 'none'}")
        log.line(f"[INFO] Config command: {self.config_cmd or 'none'}")
        log.line(f"[INFO] Config choices: {self.config_expect_choices or 'none'}")
        log.line(f"[INFO] Build command : {self.build_cmd}")
        log.line(f"[INFO] Required cmds : {self.required_commands}")
        log.line(f"[INFO] PATH prepend  : {self.path_prepend or 'none'}")
        log.line(f"[INFO] LD lib prepend: {self.ld_library_path_prepend or 'none'}")
        log.line(f"[INFO] Repo dir      : {self.repo_dir}")
        log.line(f"[INFO] Failure rpt   : {self.failure_report}")
        log.line()
        self.hash_log.write_text("", encoding="utf-8")

        for command in self.required_commands.split():
            if not shutil.which(command, path=self._subprocess_env().get("PATH")):
                self.fail_reason = f"Required command not found: {command}"
                raise RuntimeError(self.fail_reason)

        self.current_stage = "clone_repo"
        log.line(f"[{self.project_name} clone]")
        log.line("------------------------------------------")
        if self.repo_dir.exists():
            shutil.rmtree(self.repo_dir)
        self.repo_dir.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["git", "clone"]
        if self.repo_branch:
            cmd.extend(["-b", self.repo_branch, "--single-branch"])
        cmd.extend([self.repo_url, str(self.repo_dir)])
        self._run_logged(cmd)
        branch = self.repo_branch or _git(self.repo_dir, "rev-parse", "--abbrev-ref", "HEAD")
        self.main_repo_commit = _git(self.repo_dir, "rev-parse", "HEAD")
        self._append_hash(self.project_name, branch, self.main_repo_commit, self.repo_dir, self.repo_url)

        if self.product_config:
            self.current_stage = "apply_product_config"
            log.line()
            log.line("[Product config]")
            log.line("------------------------------------------")
            product_path = self.repo_dir / "products" / self.product_config
            if not product_path.is_file():
                self.fail_reason = f"Product config not found: {product_path}"
                raise RuntimeError(self.fail_reason)
            shutil.copy2(product_path, self.repo_dir / ".config")

        if self.config_cmd:
            self.current_stage = "configure"
            log.line()
            log.line(f"[{self.project_name} configure]")
            log.line("------------------------------------------")
            with self.verbose_log.open("a", encoding="utf-8", errors="replace") as verbose:
                self._run_logged(["bash", "-lc", self.config_cmd], cwd=self.repo_dir, extra_fp=verbose)

        if self.config_expect_choices:
            self.current_stage = "configure"
            log.line()
            log.line(f"[{self.project_name} expect configure]")
            log.line("------------------------------------------")
            self._run_expect_config()

        self.current_stage = "build"
        log.line()
        log.line(f"[{self.project_name} build]")
        log.line("------------------------------------------")
        with self.verbose_log.open("a", encoding="utf-8", errors="replace") as verbose:
            self._run_logged(["bash", "-lc", self.build_cmd], cwd=self.repo_dir, extra_fp=verbose)
        log.line()
        log.line(f"[INFO] {self.target_name} autobuild completed successfully")

    def _run_expect_config(self) -> None:
        script = self.work_dir / f"{self.slugs.project}_{self.slugs.model}_make_config.exp"
        script.write_text(_EXPECT_CONFIG_SCRIPT, encoding="utf-8")
        script.chmod(0o755)
        with self.verbose_log.open("a", encoding="utf-8", errors="replace") as verbose:
            self._run_logged([str(script), str(self.repo_dir), self.config_expect_choices], extra_fp=verbose)

    def _append_hash(self, key: str, branch: str, commit: str, repo_dir: Path, url: str) -> None:
        line = f"{key}|{branch}|{commit}|{repo_dir}|{url}"
        assert self.logger is not None
        self.logger.line(line)
        with self.hash_log.open("a", encoding="utf-8") as fp:
            fp.write(line + "\n")

    def _run_logged(self, cmd: list[str], cwd: Path | None = None, extra_fp=None) -> None:
        assert self.logger is not None
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
        if rc != 0:
            raise RuntimeError(f"Command failed: {' '.join(shlex.quote(part) for part in cmd)}")

    def _subprocess_env(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.path_prepend:
            env["PATH"] = f"{self.path_prepend}:{env.get('PATH', '')}"
        if self.ld_library_path_prepend:
            current = env.get("LD_LIBRARY_PATH", "")
            env["LD_LIBRARY_PATH"] = self.ld_library_path_prepend + (f":{current}" if current else "")
        return env

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

        if (self.repo_dir / ".git").is_dir():
            try:
                self.main_repo_meta = last_commit(self.repo_dir)
            except Exception:
                self.main_repo_meta = {"commit": self.main_repo_commit, "author": "", "date": "", "subject": ""}

        summary = {
            "TARGET_NAME": self.target_name,
            "RUN_TS": self.run_ts,
            "MODEL_LINEUP": self.model_lineup,
            "OS_PROJECT_NAME": self.project_name,
            "OS_REPO_URL": self.repo_url,
            "OS_REPO_BRANCH": self.repo_branch,
            "OS_PRODUCT_CONFIG": self.product_config,
            "OS_BUILD_VARIANT": self.build_variant,
            "OS_CONFIG_CMD": self.config_cmd,
            "OS_CONFIG_EXPECT_CHOICES": self.config_expect_choices,
            "OS_BUILD_CMD": self.build_cmd,
            "OS_REQUIRED_COMMANDS": self.required_commands,
            "OS_PATH_PREPEND": self.path_prepend,
            "OS_LD_LIBRARY_PATH_PREPEND": self.ld_library_path_prepend,
            "OS_TARGET_NAME": self.os_target_name,
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
            "MAIN_REPO_URL": self.repo_url,
            "MAIN_REPO_DIR": str(self.repo_dir),
            "MAIN_REPO_COMMIT": self.main_repo_commit,
            "MAIN_REPO_LAST_COMMIT": self.main_repo_meta.get("commit", ""),
            "MAIN_REPO_LAST_AUTHOR": self.main_repo_meta.get("author", ""),
            "MAIN_REPO_LAST_DATE": self.main_repo_meta.get("date", ""),
            "MAIN_REPO_LAST_SUBJECT": self.main_repo_meta.get("subject", ""),
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
            f"{self.target_name} Build Failure Report",
            "==========================================",
            f"Repo path      : {self.repo_dir}",
            f"Build log      : {self.build_log}",
            f"Verbose log    : {self.verbose_log}",
            f"Source log     : {source_log}",
            f"Generated at   : {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"Current stage  : {self.current_stage}",
            f"Fail reason    : {self.fail_reason}",
        ]
        if self.failure_analysis:
            report.extend(["", "[Failure analysis]", self.failure_analysis])
        report.extend(["", "[Recent errors]"])
        error_re = re.compile(r"CMake Error|fatal error:|\s+error:|No such file or directory|cannot find|undefined reference|ninja: build stopped|make(\[[0-9]+\])?: \*\*\*|FAILED:")
        report.extend([line for line in text.splitlines() if error_re.search(line)][-40:])
        report.extend(["", "[Recent commits]"])
        if (self.repo_dir / ".git").is_dir():
            report.extend(_git(self.repo_dir, "log", "--oneline", "-n", "20", check=False).splitlines())
        self.failure_report.write_text("\n".join(report) + "\n", encoding="utf-8")

    def _extract_failure_analysis(self, text: str) -> str:
        patterns = [
            r"CMake Error",
            r"fatal error:",
            r"\s+error:",
            r"undefined reference",
            r"cannot find",
            r"No such file or directory",
            r"ninja: build stopped",
            r"make(\[[0-9]+\])?: \*\*\*",
            r"FAILED:",
        ]
        combined = re.compile("|".join(patterns))
        for line in text.splitlines():
            if combined.search(line) and "warning:" not in line:
                return line.strip()
        return ""


_EXPECT_CONFIG_SCRIPT = r'''#!/usr/bin/expect -f
set timeout -1
log_user 1

set repo_dir [lindex $argv 0]
set choices [split [lindex $argv 1] " "]
set choice_index 0

proc next_choice {choicesVar indexVar} {
    upvar $choicesVar choices
    upvar $indexVar index

    if {$index >= [llength $choices]} {
        send_user "\n===== UNEXPECTED CHOICE PROMPT =====\n"
        exit 1
    }

    set answer [lindex $choices $index]
    incr index
    send -- "$answer\r"
}

spawn bash

expect -re {[$#] $}
send -- "cd -- \"$repo_dir\"\r"

expect -re {[$#] $}
send -- "set -o pipefail; make config; printf '\\n__CONFIG_RC__:%s\\n' \$?\r"

expect_before {
    -re {Default all settings .*([:]|\(NEW\))\s*$} { send -- "y\r"; exp_continue }
    -re {Customize Kernel Settings .*([:]|\(NEW\))\s*$} { send -- "n\r"; exp_continue }
    -re {Customize Application/Library Settings .*([:]|\(NEW\))\s*$} { send -- "n\r"; exp_continue }
    -re {Update Default Vendor Settings .*([:]|\(NEW\))\s*$} { send -- "n\r"; exp_continue }
    -re {choice\[[0-9\-?]+\]:\s*$} { next_choice choices choice_index; exp_continue }
    -re {\([A-Za-z0-9_]+\)\s+\[[^]]+\]\s*$} { send -- "\r"; exp_continue }
}

expect {
    -re {__CONFIG_RC__:0} {
        send_user "\n===== CONFIG SUCCESS =====\n"
        exit 0
    }
    -re {__CONFIG_RC__:[1-9][0-9]*} {
        send_user "\n===== CONFIG FAIL =====\n"
        exit 1
    }
    timeout {
        send_user "\n===== CONFIG TIMEOUT =====\n"
        exit 1
    }
}
'''


def run(args) -> int:
    build = OSBuild(args.config)
    if getattr(args, "dry_run", False):
        return build.dry_run()
    return build.run()
