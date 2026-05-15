# dailybuild

Python migration of the GCT daily autobuild tools.

The current goal is to validate the Python flow under the `jamesahn` account
before replacing the existing daily autobuild operation. The main build entry
points, scheduling, status parsing, upload, mail, and operational checks now
run from Python while the legacy shell repository remains available as the
reference implementation during the transition.

## Current Status

Implemented:

- Single Python entrypoint: `autobuild.py`
- One-time daily test scheduler: `test-once`
- Cron entry generator: `install-cron --dry-run`
- Native Python build runners: `run-openwrt`, `run-os`, `run-zephyros`
- Per-target build lock guards
- Combined live log viewer: `tail-logs`
- Daily status generation from `latest_summary.env`
- Samba upload packaging
- `FW_build_info_YYYYMMDD.txt` generation
- HTML mail notification
- Upload/mail duplicate guards
- Unit tests for status, upload, mail, log tailing, and runner lock behavior

Recently changed:

- Python workspace separated from the legacy autobuild workspace.
- Build lock names now use config file stems to avoid parallel target collisions.
- `FW_build_info_YYYYMMDD.txt` now includes `PASS` / `FAIL` / `N/A`.
- Failed builds include `Failure analysis` in `FW_build_info_YYYYMMDD.txt`.
- `upload_manifest.txt` is no longer uploaded to Samba.

Pending validation:

- Current one-time test run from `RUN_TS=20260513_145122`.
- Confirm LinuxOS no longer skips because of lock collision.
- Confirm mail is sent only to `jamesahn@gctsemi.com` with `[TestPy]` prefix.
- Confirm Samba upload layout under the James test folder.
- If one-time test is stable, switch daily test start time to 03:00 and install cron.

## Workspace

This repository is intended to run under:

```text
/home/jamesahn/gct-build-tools/dailybuild
```

The legacy reference repository remains available at:

```text
/home/jamesahn/gct-build-tools/autobuild
```

Python dailybuild runtime data is separated under:

```text
/home/jamesahn/gct_workspace/dailybuild
```

Runtime subdirectories:

```text
/home/jamesahn/gct_workspace/dailybuild/logs
/home/jamesahn/gct_workspace/dailybuild/repos
/home/jamesahn/gct_workspace/dailybuild/state
/home/jamesahn/gct_workspace/dailybuild/tmp
```

The old legacy workspace remains separate:

```text
/home/jamesahn/gct_workspace/autobuild
```

## Runtime Policy

Temporary Python test operation uses:

```text
MAIL_TO='jamesahn@gctsemi.com'
REPORT_SUBJECT_PREFIX='[TestPy]'
SAMBA_UPLOAD_LOCAL_DIR='/mnt/jamesahn_netk/ENG/ENG05/CS_team/James'
SAMBA_UPLOAD_UNC_ROOT='K:\ENG\ENG05\CS_team\James'
```

This keeps test mail and Samba upload separated from the existing `gct`
operation.

## Commands

Run one-time daily test:

```bash
./autobuild.py test-once
```

One-time build jobs start one minute after scheduling by default. Override with
`START_AFTER_MINUTES` when a longer delay is needed.

Preview one-time daily test schedule:

```bash
./autobuild.py test-once --dry-run
```

One-time tests stop scheduling notifier retries after 180 minutes by default.
Every scheduled one-time command also has an expiry guard, so delayed commands
exit without upload or mail after the timeout. Override with
`TEST_ONCE_MAX_RUNTIME_MINUTES` when needed.

View all build logs together:

```bash
./autobuild.py tail-logs
```

View current log tails and exit:

```bash
./autobuild.py tail-logs --lines 20 --no-follow
```

Show current job / scheduler state:

```bash
./autobuild.py list-jobs
```

Show managed runtime configuration:

```bash
./autobuild.py show-config
```

Launch the interactive operations menu:

```bash
./autobuild.py interactive
```

Inside `interactive`, you can:

- view current config
- update common config values without editing files directly
- view daily status for a run date
- view current cron / one-time / running job state

Update common operational settings:

```bash
./autobuild.py set-config --mail-to jamesahn@gctsemi.com --subject-prefix "[TestPy]" --show-after
./autobuild.py set-config --test-mail-to jamesahn@gctsemi.com --test-subject-prefix "[TestPy]"
./autobuild.py set-config --set START_AFTER_MINUTES=1 --set TEST_ONCE_MAX_RUNTIME_MINUTES=180
```

Show summarized daily status:

```bash
./autobuild.py show-status --run-date 20260515
./autobuild.py show-status --run-date 20260515 --raw
```

Run one target manually:

```bash
./autobuild.py run-openwrt --config config/openwrt_v1.00_autobuild.env
./autobuild.py run-openwrt --config config/openwrt_master_autobuild.env
./autobuild.py run-os --config config/gdm7275x_linuxos_master_autobuild.env
./autobuild.py run-zephyros --config config/zephyros_autobuild.env
```

Generate daily status:

```bash
./autobuild.py status --run-date 20260513
```

Upload logs and images:

```bash
./autobuild.py upload --run-date 20260513
./autobuild.py upload --run-date 20260513 --force
```

Send report mail:

```bash
./autobuild.py notify --run-date 20260513
./autobuild.py notify --run-date 20260513 --force
```

Preview cron entries:

```bash
./autobuild.py install-cron --dry-run
```

Install cron entries:

```bash
./autobuild.py install-cron
```

Show command help:

```bash
./autobuild.py --help
./autobuild.py set-config --help
./autobuild.py show-status --help
```

The generated cron schedule starts daily build tests at `03:00`, then launches
the remaining targets at one-minute intervals through `03:06`.

## Upload Output

Samba upload target:

```text
K:\ENG\ENG05\CS_team\James\<YYYYMMDD>
```

One-time test uploads are separated from the daily folder to avoid overwriting
daily results or another one-time run from the same date:

```text
K:\ENG\ENG05\CS_team\James\Test\<YYYYMMDD_HHMMSS>
```

The upload package includes `FW_build_info_<YYYYMMDD>.txt` and model-grouped
output directories:

```text
FW_build_info_<YYYYMMDD>.txt
GDM7275X/
GDM7243A/
GDM7243ST/
GDM7243i/
```

Each build target uploads the full run log directory referenced by the daily
status file `Log path` field:

```text
GDM7275X/openwrt_v100/Log/
GDM7275X/openwrt_master/Log/
GDM7275X/linuxos_master/Log/
GDM7275X/Zephyros/Log/
GDM7243A/uTKernel/Log/
GDM7243ST/uTKernel/Log/
GDM7243i/zephyr_v2.3/Log/
```

Typical files under each `Log/` directory:

```text
build.log
build_verbose.log
hashes.log
summary.env
failure_report.log
```

Successful build targets also upload images. Failed build targets upload logs
only and do not upload `Image/` files.

Default image upload rules:

```text
GDM7275X/openwrt_v100/Image/
  bin/targets/gdm7275x/generic/owrt*.*

GDM7275X/openwrt_master/Image/
  bin/targets/gdm7275x/generic/owrt*.*

GDM7275X/linuxos_master/Image/
  images/*

GDM7275X/Zephyros/Image/
  images/build/<ZEPHYROS_CONFIG_NAME>/zephyr/tk.gz
  images/build/<ZEPHYROS_CONFIG_NAME>/zephyr/zephyr.elf

GDM7243A/uTKernel/Image/
  tk.gz
  disa

GDM7243ST/uTKernel/Image/
  tk.gz
  disa

GDM7243i/zephyr_v2.3/Image/
  images/build/<OS_BUILD_VARIANT>/zephyr/zephyr.bin
  images/build/<OS_BUILD_VARIANT>/zephyr/zephyr.elf
```

If a target summary defines `ARTIFACT_PATHS`, those paths override the default
image upload rules for that target.

`FW_build_info_<YYYYMMDD>.txt` is grouped by model and includes:

```text
[GDM7275X]

  - OpenWRT v1.00 : PASS
    commit : ...
    author : ...
    date   : ...
    subject: ...

  - OpenWRT master : FAIL
    commit : ...
    author : ...
    date   : ...
    subject: ...
    Failure analysis : ...
```

`upload_manifest.txt` is intentionally not uploaded.

## Layout

```text
autobuild.py             CLI entrypoint
config/                  env-style runtime configs
autobuild/config.py      env/config loading and shared paths
autobuild/runner.py      OpenWrt / OS / Zephyros runner adapters
autobuild/status.py      summary/status parsing and FW_build_info generation
autobuild/upload.py      Samba/local upload packaging
autobuild/mail.py        HTML mail generation and SMTP delivery
autobuild/scheduler.py   cron and one-time test adapters
autobuild/logtail.py     combined multi-log tail viewer
autobuild/gitinfo.py     commit metadata helpers
```

## Tests

```bash
python3 -m unittest discover -s tests
```
