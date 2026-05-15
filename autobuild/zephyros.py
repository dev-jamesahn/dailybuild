"""Native Python Zephyros autobuild runner."""

from __future__ import annotations

import datetime as dt
import os
import pty
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from .config import AutobuildPaths, daily_status_file, merged_env
from .gitinfo import last_commit
from .status import generate_daily_status


SHELL_PROMPT_RE = re.compile(r"(?m)[$#] $")
SELECT_PROMPT_RE = re.compile(r"Select \[[0-9-]+\]>>")
BUILD_RC_RE = re.compile(r"__BUILD_RC__:(\d+)")
ERROR_RE = re.compile(r"error:|failed|No such file or directory|cannot find|undefined reference|ninja: build stopped|CMake Error", re.IGNORECASE)


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


class ZephyrosBuild:
    def __init__(self, config_file: str | Path):
        self.config_file = Path(config_file).expanduser()
        if not self.config_file.is_file():
            raise SystemExit(f"Missing config file: {self.config_file}")

        self.env = merged_env(self.config_file, {"CONFIG_FILE": str(self.config_file)})
        self.paths = AutobuildPaths.from_env(self.env)
        self.run_ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_date = dt.datetime.now().strftime("%Y%m%d")
        self.start_epoch = int(time.time())

        self.pkg_version = self.env.get("PKG_VERSION", "0.0.0")
        self.model_lineup = self.env.get("MODEL_LINEUP", "GDM7275X")
        self.config_select = self.env.get("ZEPHYROS_CONFIG_SELECT", "7")
        self.config_name = self.env.get("ZEPHYROS_CONFIG_NAME", "gdm7259x_nsa")
        self.repo_url = self.env.get("ZEPHYROS_REPO_URL", "https://jamesahn@vcs.gctsemi.com/OS/Zephyros")

        self.repo_storage_root = Path(self.env.get("AUTOBUILD_REPO_ROOT") or self.paths.autobuild_root / "repos").expanduser()
        self.work_dir = Path(self.env.get("WORK_DIR") or self.paths.tmp_root / f"zephyros_{_run_user()}").expanduser()
        self.repo_dir = Path(self.env.get("REPO_DIR") or self.repo_storage_root / "zephyros/build").expanduser()
        self.log_root = Path(self.env.get("LOG_ROOT") or self.paths.log_root / "zephyros").expanduser()
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
        self.artifact_paths = self.env.get("ARTIFACT_PATHS") or f"images/build/{self.config_name}/zephyr/tk.gz images/build/{self.config_name}/zephyr/zephyr.elf"

        self.current_stage = "init"
        self.build_result = "FAIL"
        self.fail_reason = ""
        self.failure_analysis = ""
        self.main_repo_commit = ""
        self.main_repo_meta = {"commit": "", "author": "", "date": "", "subject": ""}
        self.logger: TeeLogger | None = None

    @property
    def target_name(self) -> str:
        return f"{self.model_lineup} Zephyros"

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
        print("native-python-zephyros-runner")
        return 0

    def _prepare_dirs(self) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.paths.state_root.mkdir(parents=True, exist_ok=True)
        self.build_log.touch()

    def _run_steps(self) -> None:
        log = self.logger
        assert log is not None
        log.line("[INFO] Zephyros autobuild started")
        log.line(f"[INFO] Workspace root: {self.paths.work_root}")
        log.line(f"[INFO] Autobuild root: {self.paths.autobuild_root}")
        log.line(f"[INFO] Run directory : {self.run_dir}")
        log.line(f"[INFO] Config file   : {self.config_file}")
        log.line(f"[INFO] Model lineup  : {self.model_lineup}")
        log.line(f"[INFO] Package ver   : {self.pkg_version}")
        log.line(f"[INFO] Repo dir      : {self.repo_dir}")
        log.line(f"[INFO] Config select : {self.config_select}")
        log.line(f"[INFO] Config name   : {self.config_name}")
        log.line(f"[INFO] Failure rpt   : {self.failure_report}")
        log.line()
        self.hash_log.write_text("", encoding="utf-8")

        if not shutil.which("git"):
            self.fail_reason = "Required command not found: git"
            raise RuntimeError(self.fail_reason)
        if not shutil.which("bash"):
            self.fail_reason = "Required command not found: bash"
            raise RuntimeError(self.fail_reason)

        self.current_stage = "clone_zephyros"
        log.line("[Zephyros clone]")
        log.line("------------------------------------------")
        if self.repo_dir.exists():
            shutil.rmtree(self.repo_dir)
        self.repo_dir.parent.mkdir(parents=True, exist_ok=True)
        self._run_logged(["git", "clone", self.repo_url, str(self.repo_dir)])
        self.main_repo_commit = _git(self.repo_dir, "rev-parse", "HEAD")
        hash_line = f"ZEPHYROS|{self.main_repo_commit}|{self.repo_dir}|{self.repo_url}"
        log.line(hash_line)
        with self.hash_log.open("a", encoding="utf-8") as fp:
            fp.write(hash_line + "\n")

        self.current_stage = "build_zephyros"
        log.line()
        log.line("[Zephyros build]")
        log.line("------------------------------------------")
        self._run_interactive_build()
        log.line()
        log.line("[INFO] Zephyros autobuild completed successfully")

    def _run_logged(self, cmd: list[str], cwd: Path | None = None) -> None:
        assert self.logger is not None
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=dict(os.environ),
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            self.logger.write(line)
        rc = proc.wait()
        if rc != 0:
            raise RuntimeError(f"Command failed: {' '.join(shlex.quote(part) for part in cmd)}")

    def _run_interactive_build(self) -> None:
        assert self.logger is not None
        master_fd, slave_fd = pty.openpty()
        env = dict(os.environ)
        env.setdefault("TERM", "xterm")
        proc = subprocess.Popen(
            ["bash"],
            cwd=self.repo_dir,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            env=env,
            close_fds=True,
        )
        os.close(slave_fd)
        buffer = ""
        try:
            buffer = self._read_until(master_fd, proc, [SHELL_PROMPT_RE.pattern], timeout=30, extra_path=None)

            self._shell_send(master_fd, f"cd -- {shlex.quote(str(self.repo_dir))}\n")
            buffer = self._read_until(master_fd, proc, [SHELL_PROMPT_RE.pattern], timeout=30, extra_path=None, buffer=buffer)

            source_cmd = f"source ./build_config.sh {shlex.quote(self.pkg_version)}\n"
            self._shell_send(master_fd, source_cmd)
            buffer = self._read_until(
                master_fd,
                proc,
                [SELECT_PROMPT_RE.pattern],
                timeout=120,
                extra_path=None,
                buffer=buffer,
            )
            if not SELECT_PROMPT_RE.search(buffer):
                self.fail_reason = "Zephyros config prompt not found"
                raise RuntimeError(self.fail_reason)

            self._shell_send(master_fd, f"{self.config_select}\n")
            buffer = self._read_until(master_fd, proc, [SHELL_PROMPT_RE.pattern], timeout=120, extra_path=None, buffer=buffer)

            build_cmd = f"set -o pipefail; ninja 2>&1 | tee -a {shlex.quote(str(self.verbose_log))}; printf '\\n__BUILD_RC__:%s\\n' $?\n"
            self._shell_send(master_fd, build_cmd)
            buffer = self._read_until(master_fd, proc, [BUILD_RC_RE.pattern], timeout=None, extra_path=self.verbose_log, buffer=buffer)
            match = BUILD_RC_RE.search(buffer)
            rc = int(match.group(1)) if match else 1
            if rc != 0:
                self.fail_reason = "ninja build failed"
                raise RuntimeError(self.fail_reason)
        finally:
            self._terminate_shell(proc, master_fd)

    def _shell_send(self, master_fd: int, text: str) -> None:
        os.write(master_fd, text.encode("utf-8"))

    def _read_until(
        self,
        master_fd: int,
        proc: subprocess.Popen,
        patterns: list[str],
        timeout: float | None,
        extra_path: Path | None,
        buffer: str = "",
    ) -> str:
        import select

        deadline = None if timeout is None else time.time() + timeout
        compiled = [re.compile(pattern) for pattern in patterns]
        extra_fp = extra_path.open("a", encoding="utf-8", errors="replace") if extra_path else None
        try:
            while True:
                for pattern in compiled:
                    if pattern.search(buffer):
                        return buffer
                if proc.poll() is not None:
                    raise RuntimeError("Interactive Zephyros shell exited unexpectedly")
                wait_for = 1.0
                if deadline is not None:
                    wait_for = max(0.1, min(1.0, deadline - time.time()))
                    if time.time() > deadline:
                        raise RuntimeError("Timed out waiting for interactive Zephyros prompt")
                ready, _, _ = select.select([master_fd], [], [], wait_for)
                if not ready:
                    continue
                chunk = os.read(master_fd, 4096).decode("utf-8", errors="replace")
                if not chunk:
                    continue
                self.logger.write(chunk)
                if extra_fp:
                    extra_fp.write(chunk)
                    extra_fp.flush()
                buffer = (buffer + chunk)[-32000:]
        finally:
            if extra_fp:
                extra_fp.close()

    def _terminate_shell(self, proc: subprocess.Popen, master_fd: int) -> None:
        try:
            if proc.poll() is None:
                self._shell_send(master_fd, "exit\n")
                proc.wait(timeout=5)
        except Exception:
            if proc.poll() is None:
                proc.send_signal(signal.SIGTERM)
        finally:
            try:
                os.close(master_fd)
            except OSError:
                pass

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

        if (self.repo_dir / ".git").is_dir():
            try:
                self.main_repo_meta = last_commit(self.repo_dir)
            except Exception:
                self.main_repo_meta = {"commit": self.main_repo_commit, "author": "", "date": "", "subject": ""}

        summary = {
            "TARGET_NAME": self.target_name,
            "RUN_TS": self.run_ts,
            "PKG_VERSION": self.pkg_version,
            "MODEL_LINEUP": self.model_lineup,
            "ZEPHYROS_CONFIG_SELECT": self.config_select,
            "ZEPHYROS_CONFIG_NAME": self.config_name,
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
            "Zephyros Build Failure Report",
            "==========================================",
            f"Repo path      : {self.repo_dir}",
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
        report.extend([line for line in text.splitlines() if ERROR_RE.search(line)][-60:])
        report.extend(["", "[Recent commits]"])
        if (self.repo_dir / ".git").is_dir():
            report.extend(_git(self.repo_dir, "log", "--oneline", "-n", "20", check=False).splitlines())
        self.failure_report.write_text("\n".join(report) + "\n", encoding="utf-8")

    def _extract_failure_analysis(self, text: str) -> str:
        for line in text.splitlines():
            if ERROR_RE.search(line):
                return line.strip()
        return ""


def run(args) -> int:
    build = ZephyrosBuild(args.config)
    if getattr(args, "dry_run", False):
        return build.dry_run()
    return build.run()
